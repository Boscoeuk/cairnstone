"""Phase 4 retrieval and brief assembly.

Policies implemented here (docs/compile-policies.md):

- P8: only active, non-duplicate facts are eligible; superseded facts resurface only
  when the question asks about history.
- P9: briefs are prefix-stable. The stable portion is the canonical entity directory,
  byte-identical across calls for the same brain and question-independent by
  construction; it occupies its own leading system message. The question-conditioned
  fact selection lives in the volatile user message — selection may vary per
  question, the prefix may not. This is what makes TensorFold's per-message-boundary
  prefix cache hit.

Phase 4 selection: facts — not pages — are indexed (FTS5 over
fact text and quote, plus cached per-fact embeddings) and scored against the question
by lexical overlap, embedding similarity, entity match and slot match; near-duplicates
collapse; a per-page diversity cap stops one entity flooding the brief; survivors are
ordered chronologically by capture timestamp.

Embeddings come from the local endpoint only (P12): http://127.0.0.1:1234/v1,
text-embedding-nomic-embed-text-v1.5, 768d. They are cached in an `embeddings` table
keyed by (subject_kind, subject_id); unchanged text is never re-embedded.
"""

import hashlib
import json
import math
import re
import struct
import urllib.error
import urllib.request

from . import store

EMBED_URL = "http://127.0.0.1:1234/v1/embeddings"
EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"

_HISTORY_WORDS = (
    "used to", "before", "previously", "earlier", "at first", "initially",
    "no longer", "history", "past", "used be", "switch", "change", "moved from",
    "used to be", "used to live", "used to work", "used to have", "used to play",
)

EMBEDDING_DIM = 768

EMBEDDINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (subject_kind, subject_id)
);
"""


def ensure_embedding_cache(conn):
    """Create the embedding cache table. Safe to call repeatedly."""
    conn.executescript(EMBEDDINGS_SCHEMA)
    conn.commit()


def is_history_question(question):
    """True when the question asks about past states, so superseded facts may resurface."""
    q = question.lower()
    return any(w in q for w in _HISTORY_WORDS)


# ------------------------------------------------------------------ embeddings

def _pack(vec):
    return struct.pack("<%df" % len(vec), *vec)


def _unpack(blob):
    return list(struct.unpack("<%df" % (len(blob) // 4), blob))


def _request_embeddings(texts):
    body = json.dumps({"model": EMBED_MODEL, "input": list(texts)}).encode("utf-8")
    req = urllib.request.Request(
        EMBED_URL, data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    vecs = [None] * len(texts)
    for item in data["data"]:
        vecs[item["index"]] = item["embedding"]
    if any(v is None for v in vecs):
        raise RuntimeError("embedding endpoint returned an incomplete batch")
    return vecs


def cached_embeddings(conn, kind, items):
    """Return {subject_id: vector} for items = [(subject_id, text)], embedding and
    caching any misses. Text is hashed into the cache key for query-kind entries so
    unchanged text is never re-embedded."""
    ensure_embedding_cache(conn)
    out = {}
    missing = []
    for subject_id, text in items:
        row = conn.execute(
            "SELECT vector FROM embeddings WHERE subject_kind = ? AND subject_id = ?",
            (kind, subject_id)).fetchone()
        if row is not None:
            out[subject_id] = _unpack(row["vector"])
        else:
            missing.append((subject_id, text))
    if missing:
        try:
            vecs = _request_embeddings([t for _, t in missing])
        except (urllib.error.URLError, OSError, RuntimeError):
            # Embeddings are an optional accelerator, not a requirement: lexical and FTS
            # scoring still rank without them. Failing the whole brief because an embedding
            # sidecar is down made cairnstone unusable offline and broke CI on a machine with no
            # local endpoints. Misses are deliberately NOT cached, so a later run with the
            # endpoint up embeds properly instead of inheriting zero vectors.
            return out
        for (subject_id, _), vec in zip(missing, vecs):
            conn.execute(
                "INSERT OR REPLACE INTO embeddings(subject_kind, subject_id, vector)"
                " VALUES (?, ?, ?)", (kind, subject_id, _pack(vec)))
            out[subject_id] = vec
        conn.commit()
    return out


def _query_key(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cosine(a, b):
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


# ----------------------------------------------------------------- diagnostic

# Phase-4 diagnostic: separates retrieval failure from answering failure. A row is
# a retrieval failure when no fact in the brief supports the gold answer; an
# answering failure when support was present but the answer was still wrong.

_MONTHS = ("january|february|march|april|may|june|july|august|september|october|"
           "november|december")
_DATE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b|\b(?:%s)\b" % _MONTHS, re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![\w.-])\d+(?:[.,]\d+)?(?![\w.-])")

_STOPWORDS = frozenset("""
a an the and or of in on at to for from by with about as is are was were be been being
do does did doing has have had what which who whom whose when where why how many much
i me my we our you your he she it they them their his her its this that these those
will would can could should shall may might must not no nor so than too very s t
""".split())


def _content_tokens(text):
    """Lowercase word tokens minus stopwords — the tokens that carry meaning."""
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS]


def gold_support_in_brief(gold, fact_texts):
    """Deterministically decide whether the brief could support the gold answer.

    A single fact supports a single-item gold when (a) the gold is a date/number and
    every date or number mention in the gold appears in the fact text, or (b) at least
    half of the gold's content tokens overlap the fact text.

    A list-like gold ("pottery, camping, painting, swimming") is scored per item: the
    brief supports it when at least half the items are covered anywhere in the brief.
    Scoring such golds per token bag labelled aggregation failures as retrieval
    failures, which misdirected tuning in phase 5. Purely lexical — no model call.
    """
    gold_text = str(gold).strip()
    items = [i.strip() for i in re.split(r",|;|\band\b", gold_text) if i.strip()]
    if len(items) >= 2:
        covered = sum(1 for i in items if _single_item_supported(i, fact_texts))
        return covered >= max(1, len(items) // 2)
    return _single_item_supported(gold_text, fact_texts)


def _single_item_supported(gold_text, fact_texts):
    dates = [m.group(0).lower() for m in _DATE_RE.finditer(gold_text)]
    numbers = [m.group(0) for m in _NUMBER_RE.finditer(gold_text)]
    gold_tokens = set(_content_tokens(gold_text))
    for text in fact_texts:
        hay = str(text).lower()
        if dates and all(d in hay for d in dates):
            return True
        if numbers and all(n in hay for n in numbers):
            return True
        if gold_tokens:
            if len(gold_tokens & set(_content_tokens(str(text)))) >= max(
                    1, len(gold_tokens) // 2):
                return True
        elif gold_text.lower() in hay:
            return True
    return False


# ---------------------------------------------------------------------- search

def eligible_facts(conn, brain_id, include_superseded=False):
    """Facts eligible for retrieval: active, not duplicates (P8). Superseded facts are
    included only when the caller explicitly asks for history."""
    sql = (
        "SELECT f.id, f.page_id, f.text, f.capture_id, f.span_start, f.span_end,"
        " f.quote, f.status FROM facts f JOIN pages p ON p.id = f.page_id"
        " WHERE p.brain_id = ? AND f.duplicate_of IS NULL")
    if include_superseded:
        sql += " AND f.status IN ('active', 'superseded')"
    else:
        sql += " AND f.status = 'active'"
    return conn.execute(sql + " ORDER BY f.id", (brain_id,)).fetchall()


def _page_texts(conn, brain_id):
    rows = conn.execute(
        "SELECT p.id, p.path, p.title, p.bucket, v.body_md FROM pages p"
        " JOIN page_versions v ON v.id = p.current_version_id"
        " WHERE p.brain_id = ? ORDER BY p.path", (brain_id,)).fetchall()
    return rows


def _fts_page_ranks(conn, query, limit=10):
    """Page ids in FTS rank order, or [] when the query is not valid FTS syntax."""
    try:
        rows = store.search_pages(conn, query, limit=limit)
    except Exception:
        return []
    return [r["id"] for r in rows]


def search(conn, brain_id, query, k=10):
    """Hybrid retrieval: FTS5 over pages plus cosine similarity over fact and page
    text using the local embedding endpoint.

    Returns up to k dicts: {"kind": "fact"|"page", "id", "score", "text", "page_id"},
    best first. Fact score = cosine(fact, query) + 0.25 * FTS bonus of its page;
    page score = cosine(page, query) + FTS bonus. Superseded facts are eligible only
    for history questions (P8).
    """
    history = is_history_question(query)
    facts = eligible_facts(conn, brain_id, include_superseded=history)
    pages = _page_texts(conn, brain_id)

    fact_items = [(str(f["id"]), f["text"]) for f in facts]
    page_items = [(str(p["id"]), (p["title"] + "\n" + (p["body_md"] or "")))
                  for p in pages]
    fact_vecs = cached_embeddings(conn, "fact", fact_items)
    page_vecs = cached_embeddings(conn, "page", page_items)
    q_vec = cached_embeddings(conn, "query", [(_query_key(query), query)]).get(_query_key(query))

    fts_ranks = _fts_page_ranks(conn, query, limit=max(k, 10))
    fts_bonus = {pid: 1.0 / (i + 1) for i, pid in enumerate(fts_ranks)}

    results = []
    for f in facts:
        vec = fact_vecs.get(str(f["id"]))
        sim = _cosine(q_vec, vec) if (q_vec is not None and vec is not None) else 0.0
        score = sim + 0.25 * fts_bonus.get(f["page_id"], 0.0)
        results.append({"kind": "fact", "id": f["id"], "score": round(score, 6),
                        "text": f["text"], "page_id": f["page_id"],
                        "status": f["status"]})
    for p in pages:
        vec = page_vecs.get(str(p["id"]))
        sim = _cosine(q_vec, vec) if (q_vec is not None and vec is not None) else 0.0
        score = sim + fts_bonus.get(p["id"], 0.0)
        results.append({"kind": "page", "id": p["id"], "score": round(score, 6),
                        "text": p["title"], "page_id": p["id"], "status": "page"})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:k]


# ----------------------------------------------------------------------- brief

def _token_estimate(text):
    """Cheap deterministic token estimate (~4 chars/token), used only for the budget
    check; the stable text itself never depends on it."""
    return max(1, len(text) // 4)


def _citation(fact):
    return "[capture %d, span %d:%d]" % (fact["capture_id"], fact["span_start"],
                                         fact["span_end"])


# Phase 6: questions that need facts combined rather than a single lookup. Two
# signals: multiple entity-like capitalised names, or an interrogative asking
# what/which + does/has/did + a named person (cross-fact aggregation).
_MULTI_HOP_RE = re.compile(
    r"\b(?:what|which)\b[^?.]*\b(?:does|did|has|is|was)\b", re.IGNORECASE)


def _looks_multi_hop(question):
    """Heuristic: does the question likely need several facts combined?"""
    words = re.findall(r"[A-Z][a-z]+", question)
    if len(set(words)) >= 2:
        return True
    return bool(_MULTI_HOP_RE.search(question))


# Phase 8A: inference support. Multi-hop and commonsense questions fail because a
# flat fact set loses the conversational context inference needs, so the brief adds
# bounded windows of the cited captures' surrounding dialogue. Caps are hard so the
# brief stays inside the token budget (P9): at most 3 windows of at most
# _CONTEXT_WINDOW_CHARS each. (config/policies.yml does not exist yet; the default
# lives here until thresholds get a shared home.)
_CONTEXT_WINDOW_CHARS = 600
_MAX_DIALOGUE_WINDOWS = 3

# Question categories (LoCoMo numbering, mirrored in eval/harness.CATEGORY_NAMES)
# that earn dialogue context.
_INFERENCE_CATEGORIES = frozenset({"multi-hop", "commonsense"})


def _wants_dialogue_context(question, category=None):
    """True when the question should get dialogue context windows. The caller's
    category label is authoritative when given; otherwise the phase-6 multi-hop
    heuristic decides (commonsense has no lexical signal)."""
    if category is not None:
        return category in _INFERENCE_CATEGORIES
    return _looks_multi_hop(question)


def _dialogue_window(conn, fact, max_chars=_CONTEXT_WINDOW_CHARS):
    """Bounded dialogue window around a fact's cited capture: the cited turn plus
    the immediately preceding and following turn from the same conversation
    (captures are one turn each, ordered by the session index in `source_ref`).

    The fact's own turn is always kept whole (truncated to max_chars if it alone is
    longer); the neighbours are trimmed head/tail to fit the cap. Returns None when
    the capture does not exist."""
    row = conn.execute(
        "SELECT content, source_ref FROM captures WHERE id = ?",
        (fact["capture_id"],)).fetchone()
    if row is None:
        return None
    ref = row["source_ref"]
    prefix, sep, idx = ref.rpartition(":")
    neighbours = []
    if sep and idx.isdigit():
        turn = int(idx)
        for other in (turn - 1, turn + 1):
            n = conn.execute(
                "SELECT content FROM captures WHERE brain_id ="
                " (SELECT brain_id FROM captures WHERE id = ?)"
                " AND source_ref = ?",
                (fact["capture_id"], "%s:%d" % (prefix, other))).fetchone()
            if n is not None:
                neighbours.append((other, n["content"]))
    neighbours.sort()

    current = row["content"]
    if len(current) > max_chars:
        return current[:max_chars]
    turn_idx = int(idx) if idx.isdigit() else 0
    budget = max_chars - len(current)
    prev = next_ = ""
    for other, text in neighbours:
        text = text.strip()
        if other < turn_idx and text:
            prev = text[-(budget // 2):] if budget > 0 else ""
            budget -= len(prev)
        elif other > turn_idx and text:
            next_ = text[:max(0, budget)] if budget > 0 else ""
            budget -= len(next_)
    parts = [p for p in (prev, current, next_) if p]
    return "\n".join(parts)


# ------------------------------------------------- question-conditioned selection

FACT_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS fact_fts USING fts5(
    fact_id UNINDEXED, page_id UNINDEXED, text
);
"""


def _ensure_fact_fts(conn):
    """Fact-level FTS5 index over fact text and quote. Rebuilt only when the facts
    table has changed since the last build; safe to call repeatedly."""
    conn.executescript(FACT_FTS_SCHEMA)
    n_facts = conn.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"]
    n_indexed = conn.execute("SELECT COUNT(*) AS n FROM fact_fts").fetchone()["n"]
    if n_indexed != n_facts:
        conn.execute("DELETE FROM fact_fts")
        conn.executemany(
            "INSERT INTO fact_fts(fact_id, page_id, text) VALUES (?, ?, ?)",
            [(r["id"], r["page_id"], r["text"] + "\n" + r["quote"])
             for r in conn.execute("SELECT id, page_id, text, quote FROM facts")])
        conn.commit()


def _fact_fts_query(question):
    """FTS5 MATCH expression: every word quoted, OR-ed, so arbitrary questions are
    valid FTS syntax."""
    return " OR ".join('"%s"' % w for w in re.findall(r"\w+", question))


def _fact_fts_ranks(conn, question, limit=20):
    """{fact_id: rank} in FTS5 rank order over fact text and quote, best (lowest
    rank) first; {} when nothing matches."""
    _ensure_fact_fts(conn)
    try:
        rows = conn.execute(
            "SELECT fact_id FROM fact_fts WHERE fact_fts MATCH ?"
            " ORDER BY rank LIMIT ?", (_fact_fts_query(question), limit)).fetchall()
    except Exception:
        return {}
    return {r["fact_id"]: i for i, r in enumerate(rows)}


def _question_type(question):
    """Interrogative type: which value type must the answering fact carry?"""
    q = question.lower()
    if re.search(r"\bwhen\b|\bwhat year\b|\bwhat date\b|\bhow long\b|\bhow old\b", q):
        return "when"
    if re.search(r"\bwhere\b", q):
        return "where"
    if re.search(r"\bwho\b|\bwhom\b|\bwhose\b", q):
        return "who"
    if re.search(r"\bhow (?:many|much)\b", q):
        return "number"
    return "general"


def _fact_slot_type(text, page_bucket):
    """The value type a fact carries: when (date), number, where (place phrase) or
    who (a claim on a people page). None when no specific type is detectable."""
    if _DATE_RE.search(text):
        return "when"
    if _NUMBER_RE.search(text):
        return "number"
    if re.search(r"\b(?:in|at|near|from)\s+[A-Z][a-z]", text):
        return "where"
    if page_bucket == "people":
        return "who"
    return None


def _slot_bonus(q_type, fact_text, page_bucket):
    """Slot match: the question's interrogative should match the value type the fact
    carries. Match earns a bonus; a detectable mismatch on a typed question earns a
    small penalty (a 'when' question answered from a dateless fact is the phase-3
    interference pattern)."""
    if q_type == "general":
        return 0.0
    if _fact_slot_type(fact_text, page_bucket) == q_type:
        return 0.15
    return -0.05


def _time_frame_tokens(question):
    """Date/year/month mentions in the question, for near-duplicate time-frame
    preference."""
    return {m.group(0).lower() for m in _DATE_RE.finditer(question)}


def _jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def select_facts(conn, brain_id, question, budget_tokens):
    """Question-conditioned fact selection (phase 4).

    Scores every eligible fact (P8) by:
    - lexical overlap between the fact and the question's content tokens;
    - embedding similarity (cached per-fact vectors, local endpoint, P12);
    - entity match: the question's subject tokens against the page title;
    - slot match: the question's interrogative vs the fact's value type;
    - an FTS5 rank bonus over the fact-level text+quote index.

    Then, deterministically:
    - collapses near-duplicates within a page (same slot rephrased — the twelve
      camping facts), keeping the fact that best matches the question's time
      frame, then the best-scoring, then the earliest capture (canonical, P7);
    - applies a diversity cap of 3 facts per page, lifted when the question names
      that page's entity, so one entity cannot flood the brief;
    - packs facts in score order until the token budget is reached;
    - orders the survivors chronologically by capture timestamp, so the brief
      carries the chronology that disambiguates dates (phase-3 diagnosis).

    Returns the selected fact rows in render order.
    """
    history = is_history_question(question)
    facts = eligible_facts(conn, brain_id, include_superseded=history)
    pages = {p["id"]: p for p in _page_texts(conn, brain_id)}
    q_tokens = set(_content_tokens(question))
    q_type = _question_type(question)
    q_key = _query_key(question)
    q_vec = cached_embeddings(conn, "query", [(q_key, question)]).get(q_key)
    fact_vecs = cached_embeddings(conn, "fact",
                                  [(str(f["id"]), f["text"]) for f in facts])
    fts_ranks = _fact_fts_ranks(conn, question)

    scored = []
    for f in facts:
        page = pages.get(f["page_id"])
        bucket = page["bucket"] if page else None
        ftoks = set(_content_tokens(f["text"]))
        lex = (len(ftoks & q_tokens) / len(q_tokens)) if q_tokens else 0.0
        vec = fact_vecs.get(str(f["id"]))
        sim = _cosine(q_vec, vec) if (q_vec is not None and vec is not None) else 0.0
        ent = 0.0
        if page:
            ent = 0.15 * len(set(_content_tokens(page["title"])) & q_tokens)
        fts_bonus = 0.25 / (fts_ranks[f["id"]] + 1) if f["id"] in fts_ranks else 0.0
        score = lex + sim + ent + _slot_bonus(q_type, f["text"], bucket) + fts_bonus
        scored.append((score, f))
    scored.sort(key=lambda t: (-t[0], t[1]["id"]))

    # Near-duplicate collapse within each page: greedily group facts whose content
    # tokens overlap heavily, keep one per group.
    by_page = {}
    for score, f in scored:
        by_page.setdefault(f["page_id"], []).append((score, f))
    q_time = _time_frame_tokens(question)
    winners = []
    for page_id in sorted(by_page):
        items = by_page[page_id]
        used = [False] * len(items)
        for i, (si, fi) in enumerate(items):
            if used[i]:
                continue
            cluster = [(si, fi)]
            used[i] = True
            ti = set(_content_tokens(fi["text"]))
            for j in range(i + 1, len(items)):
                if used[j]:
                    continue
                sj, fj = items[j]
                if _jaccard(ti, set(_content_tokens(fj["text"]))) >= 0.5:
                    cluster.append((sj, fj))
                    used[j] = True

            def _keep(t):
                s, f = t
                frame = len(q_time & {m.group(0).lower()
                                      for m in _DATE_RE.finditer(f["text"])})
                return (-frame, -s, f["id"])

            winners.append(sorted(cluster, key=_keep)[0])
    winners.sort(key=lambda t: (-t[0], t[1]["id"]))

    # Diversity cap + budget packing, in score order. The "### Records" header is
    # part of the rendered block, so it counts against the budget too.
    selected = []
    per_page = {}
    est = _token_estimate("### Records\n")
    for score, f in winners:
        page = pages.get(f["page_id"])
        named = bool(page and set(_content_tokens(page["title"])) & q_tokens)
        if not named and per_page.get(f["page_id"], 0) >= 3:
            continue
        cost = _token_estimate("- %s %s\n" % (f["text"], _citation(f)))
        if selected and est + cost > budget_tokens:
            continue
        selected.append(f)
        est += cost
        per_page[f["page_id"]] = per_page.get(f["page_id"], 0) + 1

    # Chronological order: capture timestamp, then capture id, then span.
    stamps = {r["id"]: r["captured_at"] for r in
              conn.execute("SELECT id, captured_at FROM captures")}
    selected.sort(key=lambda f: (stamps.get(f["capture_id"], ""), f["capture_id"],
                                 f["span_start"]))
    return selected


def build_brief(conn, brain_id, question, budget_tokens=4000, category=None):
    """Assemble the brief. Returns (stable_text, question_text, selected_facts).

    stable_text — the canonical entity directory (page headers), byte-identical for
    the same brain and question-independent by construction, so TensorFold's
    per-message-boundary prefix cache keeps hitting (P9). It occupies its own
    leading system message.

    question_text — the volatile user message: the question-conditioned selected
    records followed by the question. Selection varies per question; the prefix
    may not. For multi-hop and commonsense questions (phase 8A) it also carries
    bounded dialogue-context windows from the cited captures.

    category — the question's category label ("multi-hop", "commonsense", ...) when
    the caller knows it; falls back to the multi-hop heuristic otherwise.

    selected_facts — the facts selected for this question, in render order, as
    plain dicts ({id, text, quote, status, capture_id, page_id}).
    """
    pages = _page_texts(conn, brain_id)
    stable = "\n".join("## %s (%s)" % (p["title"], p["path"]) for p in pages)

    selected = select_facts(conn, brain_id, question, budget_tokens)
    if selected:
        lines = ["### Records"]
        for f in selected:
            lines.append("- %s %s" % (f["text"], _citation(f)))
        if _looks_multi_hop(question):
            # Phase 6: quotes carry the surrounding detail the compiled claim
            # abstracts away; multi-hop questions need it to combine facts.
            lines.append("\n### Supporting quotes")
            for f in selected[:8]:
                lines.append('- "%s" %s' % (f["quote"], _citation(f)))
            lines.append(
                "\n### Answering rules\n"
                "- When several records together answer the question, combine them "
                "into one answer.\n"
                "- When the question asks for a list, list every item the records "
                "support.")
        if _wants_dialogue_context(question, category):
            # Phase 8A: inference needs the surrounding conversation, not just the
            # compiled claims. Bounded windows from the cited captures; the stable
            # system message is untouched (P9).
            windows = []
            seen_captures = set()
            for f in selected:
                if f["capture_id"] in seen_captures:
                    continue
                seen_captures.add(f["capture_id"])
                window = _dialogue_window(conn, f)
                if window:
                    windows.append(window)
                if len(windows) >= _MAX_DIALOGUE_WINDOWS:
                    break
            if windows:
                lines.append("\n### Dialogue context")
                for window in windows:
                    lines.append("- %s" % window.replace("\n", " "))
        volatile = "\n".join(lines) + "\n\n### Question\n" + question
    else:
        volatile = "### Question\n" + question

    dicts = [{"id": f["id"], "text": f["text"], "quote": f["quote"],
              "status": f["status"], "capture_id": f["capture_id"],
              "page_id": f["page_id"]} for f in selected]
    return stable, volatile, dicts


# ------------------------------------------------------------------- citations

def render_citations(conn, fact_ids):
    """Expand facts to their capture `source_ref` and quote, for an evidence appendix.

    Returns a list of dicts {fact_id, text, source_ref, quote, span} in the order the
    fact ids were given; unknown ids are skipped."""
    out = []
    for fid in fact_ids:
        row = conn.execute(
            "SELECT f.id, f.text, f.span_start, f.span_end, f.quote, c.source_ref"
            " FROM facts f JOIN captures c ON c.id = f.capture_id WHERE f.id = ?",
            (fid,)).fetchone()
        if row is None:
            continue
        out.append({
            "fact_id": row["id"],
            "text": row["text"],
            "source_ref": row["source_ref"],
            "quote": row["quote"],
            "span": (row["span_start"], row["span_end"]),
        })
    return out
