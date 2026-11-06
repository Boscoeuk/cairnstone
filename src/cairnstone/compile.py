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
        if speaker_l and subj_l == speaker_l:
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
        # A transcript role ('assistant', 'user') cannot tell us who 'I' or 'you' is, so
        # the model's subject is the only identity signal available. Require grounding.
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

def dedupe(conn, brain_id):
    """Link identical claims on the same page as corroboration (policy P7).

    Phase 7B: claims are matched by evidence, not wording. The slot-key machinery
    (P6) strips numbers/dates, and trailing modifier clauses ("by adopting kids",
    "through adoption") are cut, so paraphrases of the same claim share a key. The
    earliest capture is the canonical citation; later facts stay active and carry
    `duplicate_of`. Nothing is retracted or deleted. Returns the number linked.
    """
    rows = conn.execute(
        "SELECT f.id, f.page_id, f.text FROM facts f JOIN pages p"
        " ON p.id = f.page_id WHERE p.brain_id = ? AND f.status = 'active'"
        " AND f.duplicate_of IS NULL ORDER BY f.id",
        (brain_id,),
    ).fetchall()
    canonical, linked = {}, 0
    for r in rows:
        key = (r["page_id"], _claim_key(r["text"]))
        if key in canonical:
            conn.execute("UPDATE facts SET duplicate_of = ? WHERE id = ?",
                         (canonical[key], r["id"]))
            linked += 1
        else:
            canonical[key] = r["id"]
    conn.commit()
    return linked


_CLAUSE_CUT_RE = re.compile(r"\s+(?:by|through|via)\s+", re.IGNORECASE)


def _claim_key(text):
    """A claim's evidence key: the slot-key base (value tokens removed) with trailing
    modifier clauses cut, plus the fact's value tokens and categorical words.

    Two facts are duplicates only when the same claim holds with the same value:
    '...in March' and '...in April' share a base but differ in values, so they stay
    distinct for the contradiction pass, while '...by adopting kids' and
    '...through adoption' collapse to one claim."""
    base, values = _split_subject_slot(text)
    if base is None:
        base = _norm(text).lower()
    base = _CLAUSE_CUT_RE.split(base)[0].strip()
    cat = tuple(sorted(m.group(0).lower()
                       for _, rx in _CATEGORY_SLOTS
                       for m in rx.finditer(_norm(text))))
    return (base, cat, values)


# ------------------------------------------------------------- contradictions

def supersede_contradictions(conn, brain_id):
    """Supersede older facts whose subject/slot matches but value differs.

    Phase 7C: slots come from two sources — the numeric/date machinery (a fact's
    text with its value tokens removed) and a small explicit categorical lexicon
    (relationship status). Two active facts on the same page with the same key but
    different values contradict. The newer capture wins; the older fact is
    superseded via store.supersede_fact, never deleted.
    """
    rows = conn.execute(
        "SELECT f.id, f.page_id, f.text, f.capture_id FROM facts f JOIN pages p"
        " ON p.id = f.page_id WHERE p.brain_id = ? AND f.status = 'active'"
        " ORDER BY f.id",
        (brain_id,),
    ).fetchall()
    superseded = 0
    by_page = {}
    for r in rows:
        by_page.setdefault(r["page_id"], []).append(r)
    superseded_ids = set()
    for page_id, facts in by_page.items():
        seen = {}  # slot key -> (value, row)
        for r in facts:
            for key, value in _fact_slots(r["text"]):
                prev = seen.get(key)
                if prev is not None and prev[0] != value:
                    old, new = prev[1], r
                    # Newer capture id wins (captures are inserted in order).
                    if new["capture_id"] < old["capture_id"]:
                        old, new = new, old
                    if old["id"] not in superseded_ids:
                        store.supersede_fact(conn, old["id"], new["id"])
                        superseded += 1
                        superseded_ids.add(old["id"])
                    seen[key] = (value, new)
                elif prev is None or r["id"] > prev[1]["id"]:
                    seen[key] = (value, r)
    return superseded


# Explicit categorical lexicon (phase 7C, defect D4). Deliberately small: each
# entry is a slot name and the word set that fills it. The slot key keeps the
# text BEFORE the matched word, so 'plans to become a single parent' (a plan)
# never conflicts with 'is married' (a status).
_CATEGORY_SLOTS = (
    ("relationship_status",
     re.compile(r"\b(single|married|divorced|widowed|engaged|dating)\b", re.I)),
)


def _fact_slots(text):
    """All (slot key, value) pairs a fact asserts: numeric/date slots from
    _split_subject_slot plus one entry per categorical lexicon match."""
    slots = []
    key, value = _split_subject_slot(text)
    if key is not None:
        slots.append((key, value))
    norm = _norm(text)
    for slot, rx in _CATEGORY_SLOTS:
        m = rx.search(norm)
        if m:
            prefix = _norm(norm[:m.start()]).lower()
            if prefix:
                slots.append(("cat:%s:%s" % (slot, prefix), m.group(1).lower()))
    return slots


_VALUE_RE = re.compile(r"\d+|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
                       r"[a-z]*|\b(?:monday|tuesday|wednesday|thursday|friday|"
                       r"saturday|sunday)\b", re.I)


def _split_subject_slot(text):
    """Split a fact into (subject/slot key, value tuple).

    The key is the normalised text with every number- or date-bearing token removed, so two
    facts that differ only in a value share a key. The value tuple is those tokens.

    This is deliberately conservative: 'Alice has 2 cats' and 'Alice has 3 dogs' produce
    different keys ('alice has cats' / 'alice has dogs') and are NOT treated as contradictory.
    'Billing v2 ships Mar 31' and 'Billing v2 ships Apr 30' produce the same key
    ('billing v ships') with different values, which IS a contradiction.
    """
    norm = _norm(text)
    matches = list(_VALUE_RE.finditer(norm))
    if not matches:
        return (norm.lower(), None)
    parts, values, pos = [], [], 0
    for m in matches:
        parts.append(norm[pos:m.start()])
        values.append(m.group(0).lower())
        pos = m.end()
    parts.append(norm[pos:])
    key = " ".join(" ".join(parts).split()).lower()
    if not key:
        return (None, None)
    return (key, tuple(values))


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
