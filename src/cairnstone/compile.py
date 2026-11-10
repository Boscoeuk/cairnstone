"""Phase 2 compile pipeline: capture -> extraction -> cited facts -> pages.

Anti-hallucination rule: every fact carries a `quote` that must appear
verbatim in the capture it cites. `locate` finds the span with a
deterministic substring search; if the quote is not found the fact is
rejected, never repaired by guesswork.
"""

import argparse
import json
import re
import sys
import tempfile

from . import store
from .llm import DEFAULT_BASE_URL, DEFAULT_MODEL, LLMClient, LLMError
from .retrieve import _content_tokens

BUCKETS = store.DEFAULT_BUCKETS

EXTRACTION_SYSTEM = """You extract facts from conversation captures for a \
personal memory store.

You will be given one capture: a timestamp line, then the text. Reply with ONLY a JSON \
object, no prose, no markdown fences, in exactly this shape:

{"facts": [{"text": "...", "subject": "...", "quote": "...", "bucket": "people|projects|decisions|customers|misc", "page_title": "...", "page_path": "..."}]}

Rules:
- "subject": the name of the person (or entity) the fact is about — the speaker, the \
listener, or a named third party. Resolve it from the quote's grammatical person: \
"I/my/me" means the subject is the SPEAKER; "you/your" (with no first-person marker) \
means the subject is the LISTENER, never the speaker; a named third person means the \
subject is that person. If the quote's grammatical person contradicts the subject, \
drop the fact entirely.
- "text": one self-contained fact stated in the capture.
- Atomic attribute facts for people are REQUIRED whenever the capture implies \
them: relationship status (single, married, divorced, dating), location, \
occupation, age, and family role. Emit each as its own fact, e.g. "Caroline \
is single". A direct inference is allowed only when a quote in the capture \
supports it — "I'm single" or "I plan to become a single parent" supports \
"Caroline is single" — but never invent an attribute without a supporting \
quote. The quote rule still governs: no quote, no fact.\
 The attribute must be about the subject of the page the fact is placed on: \
first-person statements ("I'm single") and third-person statements naming the \
subject ("Caroline is single") qualify. A quote that addresses someone else \
("You'll be an awesome mom", "You're so brave") describes the LISTENER, not \
the speaker — never attribute it to the subject. When the quote is about a \
third party, either omit the fact or place it on that third party's page.
- Resolve every relative time reference (yesterday, last week, next Tuesday) to an \
absolute date, using the capture's timestamp. Write dates as YYYY-MM-DD. Never leave a \
relative expression in "text".
- "quote": a VERBATIM substring of the capture TEXT (not the timestamp line) that \
supports the fact. Copy it exactly, character for character, from the capture text.
- "bucket" must be one of: people, projects, decisions, customers, misc.
- "page_path": a lowercase, hyphenated wiki path like "people/caroline".
- If the capture contains no facts, reply {"facts": []}.
- Output nothing except the JSON object."""

RETRY_SUFFIX = """

Your previous reply was not valid JSON. Reply again with ONLY the JSON \
object, no prose, no markdown fences, no trailing commas."""


class ExtractError(Exception):
    """Extraction failed after the retry; the capture is recorded as failed."""


class PolicyHalt(Exception):
    """A policy bound (P11 max_mutation_rate) was exceeded; the pass halted."""


# ---------------------------------------------------------------- extraction

def _validate_payload(payload):
    """Return the list of validated fact dicts, or None if the shape is wrong."""
    if not isinstance(payload, dict):
        return None
    facts = payload.get("facts")
    if not isinstance(facts, list):
        return None
    out = []
    for f in facts:
        if not isinstance(f, dict):
            return None
        for key in ("text", "subject", "quote", "bucket", "page_title", "page_path"):
            if not isinstance(f.get(key), str) or not f[key].strip():
                return None
        if f["bucket"] not in BUCKETS:
            return None
        out.append(f)
    return out


def _parse_json(text):
    """Parse the model reply as JSON, tolerating only code fences around the object."""
    text = (text or "").strip()
    if text.startswith("```"):
        # drop the opening fence line and any closing fence
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])


def extract(capture_text, client, captured_at=None):
    """Ask the model for facts as JSON. One retry on invalid JSON, then raise.

    The capture timestamp is passed so relative dates are resolved at compile time
    (policy P5). Returns a list of validated fact dicts.
    """
    stamped = ("Capture timestamp: %s\n\n%s" % (captured_at or "unknown", capture_text))
    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM},
        {"role": "user", "content": stamped},
    ]
    try:
        reply = client.chat(messages, max_tokens=2048, think=False)
        payload = _parse_json(reply)
        facts = _validate_payload(payload)
        if facts is not None:
            return facts
    except (LLMError, ValueError):
        pass
    # One stricter retry.
    messages[1]["content"] = stamped + RETRY_SUFFIX
    try:
        reply = client.chat(messages, max_tokens=2048, think=False)
        payload = _parse_json(reply)
        facts = _validate_payload(payload)
    except (LLMError, ValueError):
        facts = None
    if facts is None:
        raise ExtractError("invalid JSON after retry")
    return facts


# ------------------------------------------------------------------ location

_WS_RE = re.compile(r"\s+")


def _norm(text):
    return _WS_RE.sub(" ", text).strip()


def locate(capture_text, quote):
    """Exact substring search for `quote` in `capture_text`.

    Returns (start, end) real offsets into capture_text, or None. Falls back
    to a whitespace-normalised search whose match is mapped back to real
    offsets; the span always points at real capture text.
    """
    if not quote:
        return None
    idx = capture_text.find(quote)
    if idx != -1:
        return (idx, idx + len(quote))
    # Cosmetic fallback: markdown emphasis markers, unicode dashes/quotes and case are
    # formatting, not wording. A quote that differs only cosmetically is still verbatim
    # evidence, so align it on a normalised copy and map the match back to real offsets.
    # The stored span is always a substring of the capture, so P2 is not weakened.
    for fold in (False, True):
        norm_cap, pos = _norm_with_map(capture_text, fold)
        norm_quote, _ = _norm_with_map(quote, fold)
        if not norm_quote or not norm_cap:
            continue
        j = norm_cap.find(norm_quote)
        if j == -1:
            continue
        return (pos[j], pos[j + len(norm_quote) - 1] + 1)
    return None


_MARKDOWN_CHARS = frozenset("*_`#>|~")
_UNICODE_MAP = {"–": "-", "—": "-", "‘": "'", "’": "'",
                "“": '"', "”": '"', "…": "..."}


def _norm_with_map(text, fold_case=False):
    """Normalise for matching only, returning (normalised, positions) where
    positions[i] is the offset in `text` that produced normalised character i."""
    out, pos, prev_space = [], [], False
    for i, ch in enumerate(text):
        if ch in _MARKDOWN_CHARS:
            continue
        if ch.isspace():
            if out and not prev_space:
                out.append(" ")
                pos.append(i)
                prev_space = True
            continue
        prev_space = False
        mapped = _UNICODE_MAP.get(ch)
        for c in (mapped if mapped is not None else ch):
            out.append(c.lower() if fold_case else c)
            pos.append(i)
    while out and out[-1] == " ":
        out.pop()
        pos.pop()
    return "".join(out), pos


# -------------------------------------------------------------------- pages

def upsert_page(conn, brain_id, bucket, title, path):
    """Create the page, or reuse the existing one at `path`."""
    row = conn.execute(
        "SELECT id FROM pages WHERE path = ? AND brain_id = ?", (path, brain_id)
    ).fetchone()
    if row is not None:
        return row["id"]
    return store.create_page(conn, brain_id, path, bucket, title)


# ------------------------------------------------------------------- writing

def write_facts(conn, page_id, version_id, capture_id, facts):
    """Write located facts via store.add_fact. Returns (accepted, rejected).

    `rejected` is a list of (fact_text, reason) tuples. Three code-enforced guards
    run before anything is written (policy P3: the model proposes, code disposes):
    the quote must be located verbatim, the subject must match the quote's
    grammatical person (phase 7A), and the quote must share a content token with
    the claim (phase 7D weak-quote guard).
    """
    capture_text = capture_text_of(conn, capture_id)
    accepted, rejected = [], []
    for f in facts:
        span = locate(capture_text, f["quote"])
        if span is None:
            rejected.append((f["text"], "quote not found in capture"))
            continue
        speaker = _speaker_for_quote(capture_text, span)
        subject_error = _subject_error(f["subject"], speaker, f["quote"],
                                       capture_text)
        if subject_error:
            rejected.append((f["text"], subject_error))
            continue
        if _weak_quote(f["text"], f["quote"], f["subject"]):
            rejected.append((f["text"], "weak_quote: quote shares no content token "
                                        "with the fact"))
            continue
        try:
            fact_id = store.add_fact(conn, page_id, version_id, f["text"],
                                     capture_id, span[0], span[1])
        except store.StoreError as exc:
            rejected.append((f["text"], "store rejected: %s" % exc))
            continue
        accepted.append((fact_id, f))
    return accepted, rejected


def capture_text_of(conn, capture_id):
    return store.get_capture(conn, capture_id)["content"]


# ------------------------------------------------- subject resolution (7A)

_SPEAKER_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9'_]*)\s*:")

_NAME_TOKEN_RE = re.compile(r"\b[A-Z][a-z']+\b")

_FIRST_PERSON_RE = re.compile(r"\b(?:i|i'm|i've|i'd|i'll|my|me|mine|myself)\b",
                              re.IGNORECASE)
_SECOND_PERSON_RE = re.compile(r"\b(?:you|you're|you've|you'll|your|yours|yourself)\b",
                               re.IGNORECASE)

# Capitalised tokens that are not personal names (months, days, sentence starters).
_NON_NAME_CAPS = frozenset("""
    The That This There Then They What When Where Why How If But And Also Well
    Yeah Okay Ok Yes No Maybe Perhaps Anyway Anyway Wow Oh Please Thank Thanks
    Hey Hi Hello Good Bad Next Last Every Some One Two January February March
    April May June July August September October November December Monday
    Tuesday Wednesday Thursday Friday Saturday Sunday
""".split())


def _speaker_of(capture_text):
    """The capture author: captures begin 'Name: ...' (policy P1 captures are turns)."""
    m = _SPEAKER_RE.match(capture_text or "")
    return m.group(1) if m else None


_LABEL_RE = re.compile(r"(?:^|\n)\s*([A-Za-z][A-Za-z0-9'_]*)\s*:")


def _speaker_for_quote(capture_text, span):
    """The author of the turn the quote belongs to.

    Captures begin 'Name: ...'; a capture may carry several turn labels, in which
    case the quote's speaker is the nearest label at or before the quote's first
    character. Single-turn captures (the harness norm) resolve to the first label.

    `span` is the (start, end) returned by `locate()`, so the lookup uses the same
    case/format-tolerant match that produced the stored citation. Re-searching with an
    exact `find()` here would miss a quote that differs only by case, fall back to the
    first label, and attribute a multi-turn quote to the wrong speaker — which lets the
    D1 person check run against the wrong person.
    """
    labels = [(m.start(), m.group(1))
              for m in _LABEL_RE.finditer(capture_text or "")]
    if not labels:
        return None
    if span is not None:
        preceding = [name for pos, name in labels if pos <= span[0]]
        if preceding:
            return preceding[-1]
    return labels[0][1]


def _known_person_names(capture_text):
    """Names identifiable as people in this capture: the speaker plus any other
    'Name:' turn labels the capture carries."""
    names = set()
    speaker = _speaker_of(capture_text)
    if speaker:
        names.add(speaker)
    for m in re.finditer(r"(?:^|\n)\s*([A-Za-z][A-Za-z0-9'_]*)\s*:", capture_text):
        names.add(m.group(1))
    return names


def _subject_named(subject, quote):
    """True when the subject's own name appears in the quote. Stopwords are excluded: a
    subject like 'the storage layer' must not be "mentioned" by the word 'the'."""
    quote_tokens = set(_content_tokens(quote))
    return any(t in quote_tokens for t in _content_tokens(subject))


_ROLE_LABELS = frozenset("user assistant system tool human ai bot agent operator".split())


def _is_role_label(name):
    """True for transcript role labels ('user', 'assistant'). A role is not a person:
    it cannot tell us who 'I' refers to, so grammatical-person checks cannot resolve
    identity from it."""
    return bool(name) and name.strip().lower() in _ROLE_LABELS


def _same_entity(a, b):
    """True when two subject labels name the same thing ("user" / "The user" / "User")."""
    if not a or not b:
        return False

    def canon(value):
        text = _norm(str(value)).strip().strip(".,;:").lower()
        for prefix in ("the ", "a ", "an "):
            if text.startswith(prefix):
                text = text[len(prefix):]
        return text

    return canon(a) == canon(b)


def _grounded_in_quote(subject, quote):
    """True when the quote actually mentions the subject (by name or content token)."""
    if _subject_named(subject, quote):
        return True
    return _tokens_overlap(_content_tokens(subject), _content_tokens(quote))


def _subject_error(subject, speaker, quote, capture_text):
    """Return a rejection reason when the subject contradicts the quote's grammatical
    person, else None (phase 7A, enforced in code — the prompt alone is not trusted).

    Phase 12 (dogfooding on a real agent transcript): the phase-7 rule assumed every
    subject is a person speaking in a turn. Agent sessions break both assumptions —
    speakers are role labels ('assistant', 'user') and subjects are projects, phases,
    decisions and tools. Applying person grammar there rejected 80% of extracted facts.
    """
    if not subject or not str(subject).strip():
        return "subject_unresolved: no subject given"
    subj = str(subject).strip()
    subj_l = _norm(subj).lower()
    speaker_l = _norm(speaker).lower() if speaker else None
    has_person_grammar = bool(_FIRST_PERSON_RE.search(quote)
                              or _SECOND_PERSON_RE.search(quote))
    if not has_person_grammar:
        # No 'I'/'you' in the quote, so nothing claims who is speaking. What can still be
        # decided: if the quote names a different person, that person is the subject.
        mentioned = [t for t in _NAME_TOKEN_RE.findall(quote)
                     if t in _known_person_names(capture_text)]
        if mentioned:
            if any(_norm(t).lower() == subj_l for t in mentioned):
                return None
            return ("subject_mismatch: quote is about %s, not subject %r"
                    % (mentioned, subj))
        # Otherwise: a quote inside the subject's own turn belongs to the subject.
        if _same_entity(subj, speaker):
            return None
        if speaker_l and not _is_role_label(speaker):
            # A real person spoke this turn and the subject is somebody else, with
            # nothing in the quote to identify them: unresolvable, so do not guess.
            return ("subject_unresolved: quote is in %r's turn but gives no signal "
                    "for subject %r" % (speaker, subj))
        # A transcript role ('assistant'/'user') is not a candidate subject at all, so
        # there is nothing to contradict. Defer to the weak-quote guard, which still
        # requires the quote to support the claim.
        return None
    if speaker_l is None or _is_role_label(speaker):
        # Phase 13 (LongMemEval): a transcript role cannot tell us who 'I' is, but when the
        # model names that role as the subject ("the user", "assistant") the quote is
        # definitionally about the speaker of its own turn. Treating role labels as
        # unusable subjects rejected 100% of LongMemEval captures, so accept them here.
        if _same_entity(subj, speaker):
            return None
        # Otherwise the model's subject is the only identity signal available, and it has
        # to be grounded in the quote rather than invented.
        if _grounded_in_quote(subj, quote):
            return None
        return ("subject_unresolved: no person-level speaker and subject %r is not "
                "mentioned in the quote" % subj)
    if _FIRST_PERSON_RE.search(quote):
        if speaker_l and subj_l == speaker_l:
            return None
        if not speaker_l:
            return "subject_unresolved: first-person quote but the capture has no " \
                   "speaker label"
        return ("subject_mismatch: first-person quote supports only the speaker %r, "
                "not subject %r" % (speaker, subj))
    if _SECOND_PERSON_RE.search(quote):
        if speaker_l and subj_l != speaker_l:
            return None
        return ("subject_mismatch: second-person quote describes the listener, "
                "not the speaker %r" % speaker)
    if _subject_named(subj, quote):
        return None
    # Third person: when the quote names a recognisable person, the subject must be
    # that person.
    mentioned = [t for t in _NAME_TOKEN_RE.findall(quote)
                 if t in _known_person_names(capture_text)]
    if mentioned:
        if any(_norm(t).lower() == subj_l for t in mentioned):
            return None
        return ("subject_mismatch: quote is about %s, not subject %r"
                % (mentioned, subj))
    # No grammatical-person signal at all: defaulting to the speaker is safe,
    # attributing to anyone else is not resolvable.
    if speaker_l and subj_l == speaker_l:
        return None
    return "subject_unresolved: quote gives no person signal for subject %r" % subj


# ----------------------------------------------------- weak-quote guard (7D)

def _weak_quote(text, quote, subject):
    """True when the quote shares no content token with the fact's text and does not
    mention the subject's name. Phase 7D guard, relaxed in phase 8B: the audit of 10
    weak_quote rejections found 8 of 10 were valid facts, so a quote that names the
    subject now anchors the attribution even when the claim is paraphrased away from
    the quote's wording. Verbatim location is necessary, not sufficient."""
    subj_tokens = {w for w in re.findall(r"[a-z0-9]+", (subject or "").lower())}
    fact_tokens = [w for w in _content_tokens(text) if w not in subj_tokens]
    quote_tokens = [w for w in _content_tokens(quote) if w not in subj_tokens]
    if not fact_tokens or not quote_tokens:
        return False
    if _tokens_overlap(fact_tokens, quote_tokens):
        return False
    # Phase 8B relaxation: overlap with the subject's name also counts.
    return not _tokens_overlap(sorted(subj_tokens),
                               [w for w in _content_tokens(quote)])


def _tokens_overlap(a, b):
    """Exact match, or a shared prefix of >= 4 chars (crude stem: nurse/nursing)."""
    sb = set(b)
    for w in a:
        if w in sb:
            return True
        for v in sb:
            if len(w) >= 4 and len(v) >= 4 and (w.startswith(v[:4])
                                                or v.startswith(w[:4])):
                return True
    return False


# -------------------------------------------------------------------- dedupe

def _capture_clocks(conn, brain_id):
    """Ordering clock per capture: {capture_id: (known, stamp, capture_id)}.

    Phase 16 (N9): `known` is 1 only when the stamp was given explicitly
    (`captured_at_explicit = 1`) AND store.parse_timestamp can read it. An
    undated or unparseable capture must not beat dated history, so the tuple
    leads with `known`; among equals the stamp orders (parseable stamps were
    normalised to ISO UTC at write time, phase 15 N2) and the capture id breaks
    ties. Two undated captures therefore still order by their ingest stamps."""
    clocks = {}
    for r in conn.execute(
            "SELECT id, captured_at, captured_at_explicit FROM captures"
            " WHERE brain_id = ?", (brain_id,)):
        known = 1 if (r["captured_at_explicit"] == 1
                      and store.parse_timestamp(r["captured_at"]) is not None) \
            else 0
        clocks[r["id"]] = (known, r["captured_at"], r["id"])
    return clocks


def _row_clock(row, clocks):
    """The ordering clock for a fact row's capture, defaulting to a known stamp
    when the capture is missing from `clocks` (best evidence available)."""
    return clocks.get(row["capture_id"],
                      (1, row["captured_at"], row["capture_id"]))


def dedupe(conn, brain_id, commit=True):
    """Link identical claims on the same page as corroboration (policy P7).

    Phase 7B: claims are matched by evidence, not wording. The slot-key machinery
    (P6) strips numbers/dates, and trailing modifier clauses ("by adopting kids",
    "through adoption") are cut, so paraphrases of the same claim share a key.
    Later facts stay active and carry `duplicate_of`. Nothing is retracted or
    deleted. Returns the number linked.

    Phase 15 (N1): the canonical citation is the fact with the LATEST
    `captured_at` (tie-break: highest capture id, then highest fact id), not the
    lowest fact id. A re-assertion of an earlier value must be the row the
    contradiction scan reads, or a later truth is hidden as a duplicate
    (single May / married Jun / single Jul ended with "married" active).

    Phase 16 (N9): the comparison uses the capture clock (known, stamp,
    capture_id), so a dated capture is canonical over an undated one regardless
    of the stored stamp strings. Phase 16 (N10): `commit=False` leaves the
    writes uncommitted for a caller that runs the whole pass in one transaction.
    """
    rows = conn.execute(
        "SELECT f.id, f.page_id, f.text, f.capture_id, c.captured_at"
        " FROM facts f JOIN pages p ON p.id = f.page_id"
        " JOIN captures c ON c.id = f.capture_id"
        " WHERE p.brain_id = ? AND f.status = 'active'"
        " AND f.duplicate_of IS NULL ORDER BY f.id",
        (brain_id,),
    ).fetchall()
    clocks = _capture_clocks(conn, brain_id)
    canonical, linked = {}, 0
    for r in rows:
        key = (r["page_id"], _claim_key(r["text"]))
        prev = canonical.get(key)
        if prev is None:
            canonical[key] = r
            continue
        # N1: the newest capture is canonical; ties break to the higher
        # capture id (insert order), then the higher fact id. N9: "newest"
        # is the capture clock, so a dated capture beats an undated one.
        if ((_row_clock(r, clocks), r["id"])
                > (_row_clock(prev, clocks), prev["id"])):
            # The new row is canonical; the previous canonical becomes its
            # duplicate. Rows already pointing at the old canonical are
            # repointed, so `duplicate_of` always names a live canonical row
            # rather than forming a chain (a chain would leave an earlier
            # duplicate pointing at a row that is itself a duplicate).
            conn.execute("UPDATE facts SET duplicate_of = ? WHERE duplicate_of = ?",
                         (r["id"], prev["id"]))
            conn.execute("UPDATE facts SET duplicate_of = ? WHERE id = ?",
                         (r["id"], prev["id"]))
            canonical[key] = r
        else:
            conn.execute("UPDATE facts SET duplicate_of = ? WHERE id = ?",
                         (prev["id"], r["id"]))
        linked += 1
    if commit:
        conn.commit()
    return linked


_CLAUSE_CUT_RE = re.compile(r"\s+(?:by|through|via)\s+", re.IGNORECASE)

# Phase 14: near-duplicate detection was exact-text only, so 'favourite' and
# 'favorite' never linked. Common British/American spelling variants fold to
# one American form; the claim key is also reduced to word tokens so case and
# punctuation cannot split a duplicate pair.
_SPELLING_VARIANTS = {
    "favourite": "favorite", "favourites": "favorites", "favour": "favor",
    "favours": "favors", "colour": "color", "colours": "colors",
    "colourful": "colorful", "honour": "honor", "honours": "honors",
    "behaviour": "behavior", "centre": "center", "centres": "centers",
    "metre": "meter", "theatre": "theater", "organise": "organize",
    "organised": "organized", "organiser": "organizer", "realise": "realize",
    "realised": "realized", "recognise": "recognize", "apologise": "apologize",
    "analyse": "analyze", "catalogue": "catalog", "dialogue": "dialog",
    "programme": "program", "travelling": "traveling", "traveller": "traveler",
    "cancelled": "canceled", "labelled": "labeled", "modelled": "modeled",
    "defence": "defense", "licence": "license", "practise": "practice",
    "grey": "gray", "whisky": "whiskey",
}


def _fold_spelling(text):
    """Lowercase word tokens with punctuation dropped and British/American
    spelling variants folded to one form."""
    tokens = [t for t in re.findall(r"[a-z0-9]+", text.lower())]
    return " ".join(_SPELLING_VARIANTS.get(t, t) for t in tokens)


def _claim_key(text):
    """A claim's evidence key: the slot-key base (value tokens removed) with trailing
    modifier clauses cut, plus the fact's value tokens and categorical words.

    Two facts are duplicates only when the same claim holds with the same value:
    '...in March' and '...in April' share a base but differ in values, so they stay
    distinct for the contradiction pass, while '...by adopting kids' and
    '...through adoption' collapse to one claim. The base is compared on folded
    word tokens (phase 14): case, punctuation and British/American spellings
    ('favourite'/'favorite') no longer split a duplicate pair."""
    base, values = _split_subject_slot(text)
    if base is None:
        base = _norm(text).lower()
    base = _CLAUSE_CUT_RE.split(base)[0].strip()
    base = _fold_spelling(base)
    cat = tuple(sorted(_fold_spelling(m.group(0))
                       for _, rx, _advisory in _CATEGORY_SLOTS
                       for m in rx.finditer(_norm(text))))
    return (base, cat, values)


# ------------------------------------------------------------- contradictions

def supersede_contradictions(conn, brain_id):
    """Supersede older facts whose subject/slot matches but value differs.

    Phase 7C: slots come from two sources — the numeric/date machinery (a fact's
    text with its value tokens removed) and a small explicit categorical lexicon.
    Two active facts on the same page with the same key but different values
    contradict. The newer capture wins; the older fact is superseded via
    store.supersede_fact, never deleted.

    Phase 14 fixes:
    - D1: the scan is restricted to canonical rows (`duplicate_of IS NULL`), so a
      duplicate can no longer replace the canonical fact in the comparison map
      and hide a contradiction from it. One pass converges.
    - D3: "newer" is a later `captures.captured_at` — never a higher fact id.
      Phase 15 (N1): the comparison uses the latest timestamp in a fact's
      duplicate cluster, and (N5, policy P6) equal timestamps are flagged with
      neither fact superseded, not resolved by capture id.
    - D4: when the comparison swaps the rows so the older capture loses, the
      value stored in the comparison map is swapped along with the row, so the
      stored value and stored row always agree.
    - D5(b): a contradiction on an advisory slot (location, occupation) is not
      decidable by this pass; it is recorded as a `fact.contradiction_flagged`
      change event and both facts stay active.

    Returns the number of facts superseded. See _supersede_contradictions for
    the full (superseded, flagged) result.
    """
    return _supersede_contradictions(conn, brain_id)[0]


def _supersede_contradictions(conn, brain_id, commit=True):
    """Core contradiction pass. Returns (superseded, flagged).

    Phase 15 (N1): the comparison timestamp for a fact is the LATEST
    `captured_at` among the fact and its duplicates (tie-break: highest
    capture id), so a re-assertion that dedupe linked as a duplicate still
    counts as the claim's current truth. The scan reads canonical rows only
    (D1), but each canonical row's clock is its whole duplicate cluster's.

    Phase 16 (N9): every clock is the capture clock (known, stamp, capture_id)
    — both the per-fact clock and the duplicate-cluster latest — so a dated
    fact beats an undated or unparseable one regardless of the stored stamp
    strings, and the P6 equal-instant tie applies only when `known` and the
    stamp are both equal.

    Phase 16 (N11): when the older row is an event fact and the newer row is a
    state fact, the pair is not a live contradiction — the event stays active
    as history, with no supersession and no flag. An event may still supersede
    an older state, and two events supersede each other normally.

    Phase 16 (N10): `commit=False` leaves the writes uncommitted for a caller
    that runs the whole pass in one transaction.
    """
    rows = conn.execute(
        "SELECT f.id, f.page_id, f.text, f.capture_id, c.captured_at FROM facts f"
        " JOIN pages p ON p.id = f.page_id"
        " JOIN captures c ON c.id = f.capture_id"
        " WHERE p.brain_id = ? AND f.status = 'active' AND f.duplicate_of IS NULL"
        " ORDER BY f.id",
        (brain_id,),
    ).fetchall()
    clocks = _capture_clocks(conn, brain_id)
    # N1: latest clock over each canonical fact's duplicate cluster. Duplicates
    # were linked by dedupe; a fact that is its own cluster uses its own stamp.
    latest = {}
    for r in conn.execute(
            "SELECT COALESCE(f.duplicate_of, f.id) AS canon,"
            " f.capture_id, c.captured_at"
            " FROM facts f JOIN captures c ON c.id = f.capture_id"
            " JOIN pages p ON p.id = f.page_id"
            " WHERE p.brain_id = ? AND f.status = 'active'",
            (brain_id,)):
        clock = clocks.get(r["capture_id"],
                           (1, r["captured_at"], r["capture_id"]))
        cur = latest.get(r["canon"])
        if cur is None or clock > cur:
            latest[r["canon"]] = clock
    by_page = {}
    for r in rows:
        by_page.setdefault(r["page_id"], []).append(r)
    superseded_ids = set()
    superseded = flagged = 0
    # Phase 17 (F1): the comparison state resets PER PAGE, as policy P6 and the
    # phase-16 brief specify ("on the same page"). The phase-16 canonicalisation
    # work had let one `claims` dict span the whole brain, so a fact on page A
    # could supersede or flag a fact on page B ("first CI run failed" on
    # projects/alpha retired by a projects/beta fact; phase-1 vs phase-2;
    # conv-26 vs conv-30 counts). Known limitation, documented in P6: genuinely
    # contradicting pairs that live on different pages (user facts split between
    # misc/user and people/user; the Fitbit tenure supersession) are no longer
    # resolved. A future phase may key on entity rather than page.
    for page_id, facts in by_page.items():
        # slot key -> [(value, row, clock)]: every active canonical claim on
        # that slot, on this page. Phase 16 (N11): a slot can carry several
        # stale claims at once ("is married" and "spouse is Tomas" alongside a
        # later "is single"), so all of them are resolved against the current
        # truth, not just the most recently seen one.
        claims = {}
        for r in facts:
            # N1: compare with the cluster's latest clock, not the canonical
            # row's own stamp.
            clock = latest.get(r["id"]) or _row_clock(r, clocks)
            for key, value in _fact_slots(r["text"]):
                claims.setdefault(key, []).append((value, r, clock))
        for key, entries in claims.items():
            if len({_value_key(e[0]) for e in entries}) < 2:
                continue
            s, f = _resolve_slot(conn, entries, key, superseded_ids,
                                 commit=commit)
            superseded += s
            flagged += f
    return superseded, flagged


def _value_key(value):
    """A hashable comparison key for a slot value (str, token tuple, or None)."""
    if value is None:
        return ()
    if isinstance(value, str):
        return value
    return tuple(value)


def _resolve_slot(conn, entries, key, superseded_ids, commit=True):
    """Resolve one slot's disagreeing active claims. Returns (superseded, flagged).

    Phase 16: the newest claim by capture clock is the current truth. Every
    earlier claim that disagrees is superseded by it (all of them, not only the
    last seen), unless:

    - the newest clock is shared by disagreeing claims (policy P6 ambiguity):
      every disagreeing pair is flagged and nothing is superseded;
    - the older claim is an event fact and the newest is a state fact (N11):
      an event is history, so it stays active with no flag;
    - the slot is advisory (location, occupation): both stay active and the
      pair is flagged (D5b).
    """
    superseded = flagged = 0

    def _instant(e):
        # P6/N9: ambiguity is about the instant (known, stamp), never the
        # capture id — two captures can share a stamp.
        return e[2][:2]

    top_instant = max(_instant(e) for e in entries)
    top = [e for e in entries if _instant(e) == top_instant]
    if len({_value_key(e[0]) for e in top}) > 1:
        # Equal-instant ambiguity: flag each disagreeing pair, supersede none.
        pairs = set()
        for i in range(len(top)):
            for j in range(i + 1, len(top)):
                if _value_key(top[i][0]) == _value_key(top[j][0]):
                    continue
                a, b = sorted((top[i], top[j]), key=lambda e: e[1]["id"])
                pairs.add((a[1]["id"], b[1]["id"], _value_key(a[0]),
                           _value_key(b[0])))
        for a_id, b_id, a_val, b_val in sorted(pairs):
            if _write_contradiction_flag(conn, a_id, b_id, key, a_val, b_val,
                                         commit=commit):
                flagged += 1
        return superseded, flagged
    # Several rows may assert the winning value at the same instant; name the
    # lowest-id one as the replacement so the result is deterministic.
    winner = min(top, key=lambda e: e[1]["id"])
    for old_value, old_row, _old_clock in entries:
        if _value_key(old_value) == _value_key(winner[0]):
            continue
        if old_row["id"] == winner[1]["id"] or old_row["id"] in superseded_ids:
            continue
        if _is_event_fact(old_row["text"]) and not _is_event_fact(
                winner[1]["text"]):
            continue  # N11: event history is not retracted by a later state
        if _is_advisory_slot(key):
            if _write_contradiction_flag(conn, old_row["id"], winner[1]["id"],
                                         key, old_value, winner[0],
                                         commit=commit):
                flagged += 1
            continue
        store.supersede_fact(conn, old_row["id"], winner[1]["id"],
                             commit=commit)
        superseded += 1
        superseded_ids.add(old_row["id"])
    return superseded, flagged


def _write_contradiction_flag(conn, old_id, new_id, key, old_value, new_value,
                              commit=True):
    """Record an advisory contradiction between two active facts (phase 14 D5b).

    Writes one `fact.contradiction_flagged` change event, keyed on the older
    fact. Neither fact is retracted: the flag is advisory. Writing is idempotent
    — an identical event is not duplicated, so repeated consolidation passes do
    not grow the event log. Returns True when a new event was written.
    """
    payload = json.dumps({
        "contradicts": new_id,
        "slot": key,
        "values": [
            list(v) if isinstance(v, tuple) else v
            for v in (old_value, new_value)
        ],
    })
    already = conn.execute(
        "SELECT 1 FROM change_events WHERE kind = 'fact.contradiction_flagged'"
        " AND subject_id = ? AND payload_json = ? LIMIT 1",
        (old_id, payload),
    ).fetchone()
    if already:
        return False
    brain_id = conn.execute(
        "SELECT p.brain_id FROM pages p JOIN facts f ON f.page_id = p.id"
        " WHERE f.id = ?", (old_id,),
    ).fetchone()["brain_id"]
    conn.execute(
        "INSERT INTO change_events(brain_id, kind, subject_id, created_at,"
        " payload_json) VALUES (?, 'fact.contradiction_flagged', ?, ?, ?)",
        (brain_id, old_id, store._now(), payload),
    )
    if commit:
        conn.commit()
    return True


def consolidate(conn, brain_id, max_mutation_rate=None):
    """Run the whole consolidation pass over a brain without touching the model.

    The nightly entry point behind `cairnstone consolidate` (phase 14, D2):
    dedupe, then supersede contradictions and flag undecidable ones. Idempotent
    on an unchanged brain: duplicates are already linked, superseded facts have
    left the active set, and a contradiction flag is written only once.

    Phase 15 (P11): when `max_mutation_rate` is given and the pass's mutations
    (superseded + flagged) exceed that fraction of the brain's active facts,
    a `PolicyHalt` is raised for review — mass mutation usually means a policy
    bug rather than a changed world.

    Phase 16 (N10): the whole pass runs in ONE transaction. When the rate is
    exceeded the transaction is rolled back before `PolicyHalt` is raised, so
    nothing is applied: "halted for review" means the brain is untouched, and
    the next run re-attempts (and halts again) until the policy is reviewed.
    """
    active = conn.execute(
        "SELECT COUNT(*) AS n FROM facts f JOIN pages p ON p.id = f.page_id"
        " WHERE p.brain_id = ? AND f.status = 'active'", (brain_id,)
    ).fetchone()["n"]
    linked = dedupe(conn, brain_id, commit=False)
    superseded, flagged = _supersede_contradictions(conn, brain_id, commit=False)
    if max_mutation_rate is not None and active:
        mutations = superseded + flagged
        if mutations > max_mutation_rate * active:
            conn.rollback()  # N10: nothing is applied
            raise PolicyHalt(
                "consolidation mutated %d of %d active facts (%.1f%%), above "
                "max_mutation_rate %.1f%% (policy P11); halted for review — the "
                "pass was rolled back, so no mutation was applied"
                % (mutations, active, 100.0 * mutations / active,
                   100.0 * max_mutation_rate))
    conn.commit()
    return {"duplicates_linked": linked, "superseded": superseded,
            "flagged": flagged}


# Explicit categorical lexicon (phase 7C, defect D4; extended phase 14 D5).
# Each entry is (slot name, value regex, advisory). The regex's first group is
# always the slot's value; the slot key keeps the text BEFORE the match, so
# 'plans to become a single parent' (a plan) never conflicts with 'is married'
# (a status). Advisory slots (location, occupation) are contradictions this pass
# cannot decide: they are flagged, never superseded (phase 14 D5b).
#
# Phase 15 (N4): the occupation regex required a person subject and a role-noun
# complement. Identity sentences ("X is an independent reimplementation",
# "X is a local-first memory compiler") matched the old `is a|is an` and
# produced only false flags on real data. Now `is a|is an` forms an occupation
# slot only when the subject is a person name (capitalised, not a sentence
# starter) and the complement's first word is a known role noun; `works as`
# keeps its original shape. The location value stops at a preposition or comma
# so "lives in Lisbon" and "lives in Lisbon with her husband" compare equal
# (done in _slot_value via _LOCATION_TAIL_CUT).
_PERSON_PREFIX = r"[A-Z][a-z']+(?:\s+[A-Z][a-z']+)*"
_ROLE_NOUNS = frozenset("""
    nurse teacher lawyer doctor engineer artist writer designer developer
    manager dancer singer musician chef baker driver farmer pilot officer
    soldier student professor architect dentist pharmacist veterinarian
    plumber electrician carpenter mechanic journalist editor photographer
    accountant consultant analyst scientist researcher programmer therapist
    counsellor counselor librarian barista waiter waitress surgeon parent
    mom dad mother father sister brother uncle aunt grandmother grandfather
    husband wife partner freelancer contractor intern
""".split())
_CATEGORY_SLOTS = (
    ("relationship_status",
     re.compile(r"\b(single|married|divorced|widowed|engaged|dating)\b", re.I),
     False),
    ("location",
     re.compile(r"\b(?:lives in|lived in|moved to|is moving to)\b\s+(.+)$", re.I),
     True),
    ("occupation",
     re.compile(r"^(%s)\s+(?:works as|work as|working as|is)\s+(?:a|an)\s+"
                r"([a-z][a-z'-]*)\b.*$" % _PERSON_PREFIX, re.I),
     True),
)

# Phase 16 (N11): "<subject>'s spouse/husband/wife/partner is <name>" forms a
# relationship_status slot; the value is the documented inference above.
_SPOUSE_RE = re.compile(
    r"^(.+?)'s (spouse|husband|wife|partner) (?:is|was)\b\s*(.+)$", re.I)
_SPOUSE_VALUES = {"spouse": "married", "husband": "married",
                  "wife": "married", "partner": "partnered"}


def _is_role_noun(word):
    """True when the word is a known occupation/role noun (phase 15, N4)."""
    return word.lower() in _ROLE_NOUNS

_ADVISORY_SLOTS = frozenset(slot for slot, _rx, advisory in _CATEGORY_SLOTS
                            if advisory)

# Phase 15 (N4): a location value ends at a preposition or comma — "in Lisbon
# with her husband" and "in Lisbon" are the same city.
_LOCATION_TAIL_CUT = re.compile(
    r"\s+(?:with|without|near|beside|next|and|but|before|after|during|since|"
    r"until|for|from|about|around|to|in|on|at|by)\b|,", re.IGNORECASE)


def _is_advisory_slot(key):
    """True when a slot key belongs to an advisory (flag-only) lexicon entry."""
    return key.split(":")[1] in _ADVISORY_SLOTS if key.startswith("cat:") else False


# Phase 16 (N8/N11): a bounded marker regex separating life EVENTS ("moved to
# Lisbon", "got married") from STATES ("lives in Lisbon", "is married"). An
# event is history: a later state does not contradict it, so it is skipped in
# the brief's contradiction notes and left active by the supersession pass.
#
# Phase 17 (F4): "X married Y", "wed", "eloped", "separated", "engaged" and
# "relocated" are life-event phrasings the bounded list missed, so a later
# state could wrongly retire them. They are added to the marker; "married" is
# anchored to the verb-with-named-object form ("married Tomas") in
# _MARRIED_VERB_RE, because a bare "married" would also mark the state sentence
# "Caroline is married" as an event and break its retirement. The false event
# hits "met", "left" and "joined" are DROPPED from the marker (Tes's
# "drop them from the state-immunity rule" option): they hit state sentences
# ("Caroline met her husband through work and is married", "left-handed",
# "the club she joined") and made them permanently immune, and a verb-position
# anchor cannot separate "met her husband and is married" from a genuine
# "met her husband" event.
_EVENT_MARKER_RE = re.compile(
    r"\b(?:moved|moves|moving|migrated|arrived|departed|started|"
    r"began|stopped|quit|resigned|graduated|visited|travelled|traveled|"
    r"bought|sold|got married|married on|got divorced|divorced on|split up|"
    r"split from|broke up|was born|died|"
    r"wed|eloped|separated|engaged|relocated)\b", re.IGNORECASE)

_MARRIED_VERB_RE = re.compile(r"\bmarried\s+[A-Z]")


def _is_event_fact(text):
    """True when the fact text marks a life event rather than a state.

    Used by the brief's contradiction notes (N8) and by the supersession pass
    (N11): an event-and-state pair is not a live contradiction."""
    text = text or ""
    if _EVENT_MARKER_RE.search(text):
        return True
    return bool(_MARRIED_VERB_RE.search(text))


def _slot_value(slot, raw):
    """The comparable value for a lexicon match.

    Relationship status keeps its matched word. Location and occupation fold the
    tail of the sentence to content tokens with dates/numbers removed, so 'moved
    to Lisbon on 2023-05-25' and 'lives in Lisbon' carry the same value ('lisbon')
    and rewordings of the same occupation compare equal. Returns None when
    nothing comparable remains.

    Phase 15 (N4): the location value stops at a preposition or comma, so
    'lives in Lisbon' and 'lives in Lisbon with her husband' carry the same
    value — the trailing household detail is not a different city.
    """
    if slot == "relationship_status":
        return raw.lower()
    if slot == "location":
        raw = _LOCATION_TAIL_CUT.split(raw)[0].strip()
    tokens = [t for t in _content_tokens(raw) if not _VALUE_RE.fullmatch(t)]
    return tuple(tokens) or None


_COPULA_TAIL = {
    "is", "are", "was", "were", "be", "been", "being", "am",
    "got", "get", "gets", "gotten", "became", "becomes", "become",
    "has", "have", "had", "having",
    "now", "currently", "recently", "still", "also", "then", "later",
}

# Phase 17 (F4): common predicate verbs. A categorical slot's subject ends where
# the predicate starts, so the key cannot swallow a whole clause. Kept small and
# explicit rather than derived, because a wrong split would silently change slot
# keys; tokens ending in "ed" are treated as verbs too.
# Deliberately action verbs only. Planning/modal verbs ("plans", "wants",
# "hopes") are excluded so "plans to become a single parent" keeps its own slot
# (test_plan_fact_does_not_contradict_status_fact). The "ed" suffix is NOT used
# as a verb signal for the same reason ("planned" would truncate the key).
_VERB_TOKENS = {
    "met", "joined", "left", "started", "began", "moved", "relocated",
    "bought", "sold", "married", "wed", "eloped", "separated", "achieved",
    "scored", "owns", "owned", "works", "worked", "lives", "lived", "uses",
    "used", "spent", "took", "went", "made",
}

# Phase 16 (N7): the occupation branch captured "Caroline has been working as"
# as the subject, so its slot key never matched "Caroline is a nurse". These
# trailing article/verb tokens are stripped as well. Deliberately NOT here:
# "plans", "to", "become" — a plan must stay a distinct slot from a status
# (test_plan_fact_does_not_contradict_status_fact).
_SUBJECT_TAIL_EXTRAS = frozenset(
    "a an the working work works spouse husband wife partner".split())


def _subject_prefix(text):
    """The subject part of a categorical slot key.

    Phase 15: the key must identify WHO the claim is about, not the verb phrase
    used to say it. "Caroline is single" and "Caroline got married" previously
    keyed as `caroline is` and `caroline got`, so a real contradiction between
    them was never compared. Trailing copulas, auxiliaries and time adverbs are
    stripped so both key as `caroline`. Phase 16 (N7): trailing articles and
    work/role words are stripped too, and a possessive 's is removed from the
    final token ("Caroline's spouse is Tomas" keys `caroline`).

    Phase 17 (F4): stripping only TRAILING copulas still left a whole clause in
    the key — "Caroline met her husband through work and is married" keyed
    `caroline met her husband through work and`, so it never compared against
    `caroline` and the later "Caroline is single" could not retire it. The
    subject ends at the first verb, so the prefix is cut there.
    """
    tokens = text.split()
    while tokens and (tokens[-1] in _COPULA_TAIL
                      or tokens[-1] in _SUBJECT_TAIL_EXTRAS):
        tokens.pop()
    for i, tok in enumerate(tokens):
        if tok in _COPULA_TAIL or tok in _VERB_TOKENS:
            tokens = tokens[:i]
            break
    if tokens and tokens[-1].endswith("'s") and len(tokens[-1]) > 2:
        tokens[-1] = tokens[-1][:-2]
    return " ".join(tokens)


# Phase 17 (D2): a relationship category word only forms a live slot when it is
# the PREDICATE of the main clause. F4's subject cut moved every incidental
# match ("online dating", "single parent", "single-action", "engaged guests",
# "friend who is getting married", "colleague who is divorced") onto the
# subject's bare key, so a later off-topic fact superseded a true status (Tes
# review 5, D2/D3: 49 corpus texts moved onto a bare live subject key).
#
# Accepted shape: subject + copula/state verb + optional short adverb +
# category word ("Caroline is married", "The user is now dating someone",
# "Caroline got married"), where the copula is the main clause's first
# predicate or is conjoined with "and".
# Rejected: relative clauses ("who is married"), matches after a preposition or
# any non-copula word ("about online dating", "is working on ..."),
# noun modifiers ("single parent", "single-action", "engaged guests") and
# plans ("is getting married", "plans to become a single parent").
_RELATION_WORDS = frozenset("single married divorced widowed engaged dating".split())

_STATE_AUX_TOKENS = frozenset("""
    is are was were am got get gets been become becomes became has have had
""".split())

_RELATION_ADVERBS = frozenset("""
    now currently still recently already also just then later very really quite
    happily newly both not never definitely probably actually today soon again
    once yesterday
""".split())

_RELATIVE_PRONOUNS = frozenset("who which that whose whom".split())

# Function words, pronouns, adverbs and punctuation after the category word
# leave it a predicate ("married to Tomas", "dating someone", "single now",
# "got married recently"); a content word there makes it a noun modifier
# ("single parent", "engaged guests", "single-action").
_RELATION_FOLLOW_OK = frozenset("""
    a an the and or but with without to for from in on at by of about after
    before during since until as than someone somebody something anyone anybody
    anything nobody everyone everybody everything i you he she we they it me
    him her us them this these those
""".split()) | _RELATION_ADVERBS

# Punctuation right after the category word ends the predicate; what follows is
# a new clause, not a modifier.
_CLAUSE_END_PUNCT = ".,;:!?)]\"'"


def _relationship_status_slot(text):
    """(subject prefix, value) for the main-clause relationship predicate, or None.

    Phase 17 (D2/D3). See the block comment above for the accepted and rejected
    shapes. The prefix runs through `_subject_prefix`, so a coordinated main
    clause ("Caroline met her husband through work and is married") keys on
    `caroline`.
    """
    norm = _norm(text).lower()
    toks = [(m.group(0), m.start(), m.end())
            for m in re.finditer(r"[a-z0-9']+", norm)]
    words = [t[0] for t in toks]
    if not words:
        return None
    first_pred = None
    for idx, word in enumerate(words):
        if word in _STATE_AUX_TOKENS or word in _VERB_TOKENS:
            first_pred = idx
            break
    if first_pred is None:
        return None
    for i, word in enumerate(words):
        if word not in _RELATION_WORDS:
            continue
        # Copula/state verb, optionally with a short adverb, directly before it.
        if i >= 1 and words[i - 1] in _STATE_AUX_TOKENS:
            copula = i - 1
        elif (i >= 2 and words[i - 1] in _RELATION_ADVERBS
              and words[i - 2] in _STATE_AUX_TOKENS):
            copula = i - 2
        elif (i == first_pred and i >= 1
              and words[i - 1] not in _RELATIVE_PRONOUNS
              and words[i - 1] not in _RELATION_FOLLOW_OK
              and words[i - 1] not in _RELATION_ADVERBS
              and not any(w in _RELATION_WORDS for w in words[:i])):
            # Verb form: the category word is the main clause's first predicate
            # ("Caroline married Tomas", "Pocahontas married John Rolfe"). Its
            # object may be a content noun, so no modifier check here. A
            # relationship word earlier in the prefix means the clause is ABOUT
            # the status ("... includes single-vs-married"), not a predicate
            # about the subject, so that is left alone.
            prefix = _subject_prefix(" ".join(words[:i]))
            if prefix:
                return prefix, word
            continue
        else:
            continue
        # Adjective form: a content word immediately after the category word,
        # with no punctuation between, makes it a noun modifier.
        nxt = i + 1
        if nxt < len(words):
            gap = norm[toks[i][2]:toks[nxt][1]]
            if (not any(ch in _CLAUSE_END_PUNCT for ch in gap)
                    and words[nxt].isalpha()
                    and words[nxt] not in _RELATION_FOLLOW_OK):
                continue
        # Main clause only: the copula is the first predicate (possibly with a
        # leading auxiliary chain, "has been married"), or is coordinated with
        # "and" after one. This rejects subordinate/relative clauses
        # ("The user is happy that her sister is married").
        if copula == first_pred:
            pass
        elif copula >= 1 and words[copula - 1] == "and":
            pass
        elif all(w in _STATE_AUX_TOKENS or w in _RELATION_ADVERBS
                 for w in words[first_pred:copula]):
            pass
        else:
            continue
        if copula >= 1 and words[copula - 1] in _RELATIVE_PRONOUNS:
            continue
        prefix = _subject_prefix(" ".join(words[:copula]))
        if not prefix:
            continue
        return prefix, word
    return None


def _fact_slots(text):
    """All (slot key, value) pairs a fact asserts: numeric/date slots from
    _split_subject_slot plus one entry per categorical lexicon match.

    Phase 15 (N4): an `is a|is an` occupation match only counts when the
    complement's first word is a role noun; identity sentences ("X is an
    independent reimplementation") form no slot.
    """
    slots = []
    key, value = _split_subject_slot(text)
    if key is not None:
        slots.append((key, value))
    norm = _norm(text)
    for slot, rx, _advisory in _CATEGORY_SLOTS:
        if slot == "relationship_status":
            continue  # phase 17 D2: main-clause predicate rule below
        m = rx.search(norm)
        if m:
            if slot == "occupation":
                if not _is_role_noun(m.group(2)):
                    continue
                # The subject is captured inside the match (group 1); the
                # slot key must carry it, so "Caroline is a nurse" and
                # "Melanie is a nurse" never collide. Phase 16 (N7): the
                # captured subject runs through _subject_prefix, so
                # "Caroline has been working as a nurse" keys
                # cat:occupation:caroline, not ...caroline has been.
                prefix = _subject_prefix(_norm(m.group(1)).lower())
                value = _slot_value(slot, m.group(2))
            else:
                prefix = _subject_prefix(_norm(norm[:m.start()]).lower())
                value = _slot_value(slot, m.group(1))
            if prefix and value is not None:
                slots.append(("cat:%s:%s" % (slot, prefix), value))
    # Phase 17 (D2): the relationship slot comes from the main-clause predicate
    # rule, not from an anywhere-in-the-sentence lexicon match.
    rel = _relationship_status_slot(text)
    if rel is not None:
        slots.append(("cat:relationship_status:%s" % rel[0], rel[1]))
    # Phase 16 (N11): a spouse implies married — a documented inference, so
    # "Caroline's spouse is Tomas" carries the same relationship_status slot
    # (and value) as a same-time "Caroline is married" — no false flag — and
    # loses to a later "Caroline is single".
    m = _SPOUSE_RE.search(norm)
    if m:
        prefix = _subject_prefix(_norm(m.group(1)).lower())
        value = _SPOUSE_VALUES.get(m.group(2).lower())
        if prefix and value:
            slots.append(("cat:relationship_status:%s" % prefix, value))
    return slots


# Phase 16 (N7): the month alternation matched a three-letter prefix plus any
# tail, so "married" was read as the month "mar" + "ried" and the residual key
# lost its verb. Explicit optional suffixes with word boundaries on both sides
# keep "Mar 31" a month while "married" is no longer one.
_VALUE_RE = re.compile(r"\d+|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|"
                       r"apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
                       r"sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|"
                       r"dec(?:ember)?)\b|\b(?:monday|tuesday|wednesday|"
                       r"thursday|friday|saturday|sunday)\b", re.I)


# Phase 17 (F3a): a bare trailing "as of <date>" clause — "as of" followed only
# by date-ish tokens (digits with separators, month or weekday words) — is a
# provenance stamp, not claim material.
_AS_OF_DATE_TOKEN_RE = re.compile(
    r"^(?:[\d./-]+|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|"
    r"apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday)$", re.IGNORECASE)


def _strip_bare_as_of_tail(norm):
    """Drop a bare trailing "as of <date>" clause (phase 17, F3a).

    Only a BARE clause is dropped: "as of" followed by nothing but date tokens
    at the very end of the text. "As of 2026-11-05 the build sits at 83 tests"
    (leading), "as of late 2022" (not bare) and "as of the 2023-05-22 deadline"
    (not bare) are left alone.
    """
    tokens = norm.split()
    i = len(tokens)
    while i > 0 and _AS_OF_DATE_TOKEN_RE.match(tokens[i - 1]):
        i -= 1
    if (i < len(tokens) and i >= 2
            and tokens[i - 2].lower() == "as"
            and tokens[i - 1].lower() == "of"):
        return " ".join(tokens[:i - 2])
    return norm


# Phase 17 (D1): the identifier rule is INVERTED from F3b. A digit is part of a
# NAME only when it is attached to a word ("b600", "v2"), hyphen-joined to a
# label ("conv-26", "phase-1"), or preceded by a short identifier label
# ("phase 1", "budget 600", "n=12"). Any other preceding word — a verb, a
# quantifier, an adjective — leaves the number as a VALUE that changes over
# time. F3b's first cut treated every non-boilerplate word as a label, which
# froze counts into the slot key: "owns 15" and "owns 17" keyed apart, so a
# genuine knowledge update never superseded (Tes review 5, D1: 8 of 12 count
# updates stopped resolving; 264 corpus keys had a verb or quantifier as the
# "label").
# Phase 17 (D5): progress nouns were taken off this list because a position
# after them changes over time ("on page 120" → "on page 310", "reached level
# 30" → "level 45"); those numbers are values, not names, so a later position
# supersedes. "Chapter 2: …" / "Chapter 3: …" still key apart because the
# titles differ.
_IDENTIFIER_LABELS = frozenset("""
    phase conv sample budget n v version tier port pid issue id pr section
    question task ticket sprint wave epoch model commit class batch trial arm
    condition
""".split())


def _is_identifier_digit(norm, match):
    """True when the digit match is part of a name, not a value (F3b/D1).

    Three signals: the digits are attached to a preceding word ("b600", "v2"),
    hyphen-joined to a label ("conv-26", "phase-1"), or the preceding token is
    on the short identifier-label list ("phase 1", "budget 600", "n=12"). Every
    other preceding word leaves the digits a value ("owns 15", "ran 5 km",
    "over 30", "saved 300", "for 6 months", "in 2022", "has 1 child", "1,613").
    """
    start = match.start()
    if start > 0 and norm[start - 1].isalpha():
        return True
    if start > 1 and norm[start - 1] == "-" and norm[start - 2].isalpha():
        return True
    label = re.search(r"([A-Za-z]+)[^A-Za-z]*$", norm[:start])
    if not label:
        return False
    return label.group(1).lower() in _IDENTIFIER_LABELS


def _split_subject_slot(text):
    """Split a fact into (subject/slot key, value tuple).

    The key is the normalised text with every number- or date-bearing token removed, so two
    facts that differ only in a value share a key. The value tuple is those tokens.

    This is deliberately conservative: 'Alice has 2 cats' and 'Alice has 3 dogs' produce
    different keys ('alice has cats' / 'alice has dogs') and are NOT treated as contradictory.
    'Billing v2 ships Mar 31' and 'Billing v2 ships Apr 30' produce the same key
    ('billing v ships') with different values, which IS a contradiction.

    Phase 17 (F3a): a bare trailing "as of <date>" clause is a provenance stamp,
    not part of the claim, so it is stripped before matching: its date tokens
    are neither a value nor key material, and "X" and "X as of 2023-05-22" key
    and compare as one claim.

    Phase 17 (F3b): digits that are part of a name stay in the KEY. A digit
    directly attached to a word ("b600", "v2") or preceded by a content word
    that labels it ("phase 1", "conv-26", "budget 600", "n=12") identifies
    WHICH thing the claim is about; it is not a value that changes over time.
    Digits after boilerplate, prepositions or month/weekday tokens ("for 6
    months", "in 2022", "on 2023-05-08", "has 1 child") remain values.
    """
    norm = _norm(text)
    norm = _strip_bare_as_of_tail(norm)
    matches = list(_VALUE_RE.finditer(norm))
    if not matches:
        # Phase 16 (N7): the key is canonicalised here too, so "Caroline is
        # single" and "Caroline is single now" share a slot key instead of
        # carrying the extractor's phrasing.
        return (_canonical_slot_key(norm.lower()) or None, None)
    parts, values, pos = [], [], 0
    for m in matches:
        if (m.group(0)[0].isdigit() and _is_identifier_digit(norm, m)):
            continue  # F3b: part of a name — stays in the key text
        parts.append(norm[pos:m.start()])
        values.append(m.group(0).lower())
        pos = m.end()
    parts.append(norm[pos:])
    key = _canonical_slot_key(" ".join(" ".join(parts).split()).lower())
    if not key:
        return (None, tuple(values) or None)
    return (key, tuple(values) or None)


# Phase 16 (N7): the residual key carried the extractor's phrasing ("has been
# working as", "as of - - ."), so paraphrases of one claim never shared a slot
# key and stale values stayed active. Canonicalise it to the claim's content:
# word tokens only, no possessives, no copula/auxiliary boilerplate, plural
# nouns folded to one form.
_SLOT_KEY_TOKEN_RE = re.compile(r"[a-z0-9']+")

_SLOT_KEY_BOILERPLATE = frozenset("""
    a an the is are was were be been being am has have had having as of for
    since during working now currently recently still also then later
""".split())

_IRREGULAR_SINGULARS = {
    "children": "child", "people": "person", "men": "man", "women": "woman",
    "feet": "foot", "teeth": "tooth", "mice": "mouse",
}


def _canonical_slot_key(residual):
    """Canonical form of a residual slot key: content tokens only.

    Drops punctuation fragments, possessive 's, boilerplate copulas/auxiliaries
    and time-adverb filler, and singularises plural nouns (irregulars via map,
    otherwise a trailing s on tokens of length >= 4 not ending in ss/us/is)."""
    tokens = []
    for tok in _SLOT_KEY_TOKEN_RE.findall(residual):
        if tok.endswith("'s") and len(tok) > 2:
            tok = tok[:-2]
        if tok in _SLOT_KEY_BOILERPLATE:
            continue
        tok = _IRREGULAR_SINGULARS.get(tok, tok)
        if (len(tok) >= 4 and tok.endswith("s")
                and not tok.endswith(("ss", "us", "is"))):
            tok = tok[:-1]
        tokens.append(tok)
    return " ".join(tokens)


# ------------------------------------------------------------------- compile

def compile_capture(conn, brain_id, capture_id, client):
    """Compile one capture. Returns a per-capture result dict."""
    capture = store.get_capture(conn, capture_id)
    try:
        facts = extract(capture["content"], client, captured_at=capture["captured_at"])
    except ExtractError as exc:
        return {"capture_id": capture_id, "ok": False, "reason": str(exc),
                "accepted": 0, "rejected": []}
    accepted, rejected = [], []
    # Group facts by page so each page is upserted once.
    by_page = {}
    for f in facts:
        by_page.setdefault((f["bucket"], f["page_title"], f["page_path"]), []) \
            .append(f)
    for (bucket, title, path), group in by_page.items():
        page_id = upsert_page(conn, brain_id, bucket, title, path)
        version_id = conn.execute(
            "SELECT current_version_id FROM pages WHERE id = ?", (page_id,)
        ).fetchone()["current_version_id"]
        acc, rej = write_facts(conn, page_id, version_id, capture_id, group)
        accepted.extend(acc)
        rejected.extend(rej)
    # Phase 14, D2: record that this capture has been extracted, so a nightly
    # `compile` never re-processes it (no duplicate facts, no extra model calls).
    store.mark_capture_compiled(conn, capture_id)
    return {"capture_id": capture_id, "ok": True, "reason": None,
            "accepted": len(accepted), "rejected": rejected}


def compile_all(conn, brain_id, capture_ids, client):
    """Compile a list of captures, then dedupe and supersede. Returns summary."""
    results = [compile_capture(conn, brain_id, cid, client) for cid in capture_ids]
    dupes = dedupe(conn, brain_id)
    superseded = supersede_contradictions(conn, brain_id)
    return {
        "captures": len(results),
        "failed_captures": [r["capture_id"] for r in results if not r["ok"]],
        "facts_accepted": sum(r["accepted"] for r in results),
        "facts_rejected": [(r["capture_id"], text, reason)
                           for r in results for text, reason in r["rejected"]],
        "duplicates_linked": dupes,
        "superseded": superseded,
    }


def uncited_facts(conn, brain_id):
    """Count active facts whose quote does not appear in their capture."""
    rows = conn.execute(
        "SELECT f.id, f.quote, c.content FROM facts f"
        " JOIN pages p ON p.id = f.page_id"
        " JOIN captures c ON c.id = f.capture_id"
        " WHERE p.brain_id = ? AND f.status = 'active'", (brain_id,)
    ).fetchall()
    bad = [r["id"] for r in rows if r["quote"] not in r["content"]]
    return bad


# ---------------------------------------------------------------------- CLI

def _load_smoke_captures(path, limit=10):
    """First conversation, first `limit` turns, as (text, session timestamp) pairs.

    The timestamp is required: policy P5 resolves relative dates at compile time, so a
    capture without one cannot be compiled honestly.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    conv = data[0]["conversation"]
    stamp = conv.get("session_1_date_time", "unknown")
    session = conv["session_1"]
    return [("%s: %s" % (t["speaker"], t["text"]), stamp) for t in session[:limit]]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cairnstone.compile",
                                     description="Compile captures into cited pages")
    parser.add_argument("--smoke", action="store_true",
                        help="compile ~10 LoCoMo captures into a temp DB")
    parser.add_argument("--dataset", default="eval/datasets/locomo10.json")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args(argv)

    if not args.smoke:
        parser.error("only --smoke is implemented in phase 2")

    client = LLMClient(base_url=args.base_url, model=args.model)
    with tempfile.TemporaryDirectory() as tmp:
        conn = store.init_db(tmp + "/smoke.db")
        ws = store.create_workspace(conn, "smoke")
        brain = store.create_brain(conn, ws, "smoke", "smoke")
        texts = _load_smoke_captures(args.dataset)
        capture_ids = [
            store.add_capture(conn, brain, "conversation", t, "locomo10:smoke:%d" % i,
                              captured_at=stamp)
            for i, (t, stamp) in enumerate(texts)
        ]
        summary = compile_all(conn, brain, capture_ids, client)
        uncited = uncited_facts(conn, brain)
        pages = conn.execute(
            "SELECT COUNT(*) AS n FROM pages WHERE brain_id = ?", (brain,)
        ).fetchone()["n"]

    print("captures in: %d" % summary["captures"])
    print("failed captures: %s" % (summary["failed_captures"] or "none"))
    print("facts accepted: %d" % summary["facts_accepted"])
    print("facts rejected: %d" % len(summary["facts_rejected"]))
    for cid, text, reason in summary["facts_rejected"]:
        print("  - capture %d: %r (%s)" % (cid, text[:80], reason))
    print("duplicates linked: %d" % summary["duplicates_linked"])
    print("superseded: %d" % summary["superseded"])
    print("pages created: %d" % pages)
    print("uncited facts: %d (must be 0)" % len(uncited))
    print("engine telemetry (last call): %s" % json.dumps(client.telemetry_last()))
    return 0 if not uncited else 1


if __name__ == "__main__":
    sys.exit(main())
