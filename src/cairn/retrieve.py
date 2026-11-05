"""Phase 3 retrieval and brief assembly.

Policies implemented here (docs/compile-policies.md):

- P8: only active, non-duplicate facts are eligible; superseded facts resurface only
  when the question asks about history.
- P9: briefs are prefix-stable. The stable portion is the compiled canonical content,
  byte-identical across calls for the same brain, and is question-independent by
  construction — the question never influences which content is kept, only the volatile
  user message. This is what makes TensorFold's per-message-boundary prefix cache hit.

Embeddings come from the local endpoint only (P12): http://127.0.0.1:1234/v1,
text-embedding-nomic-embed-text-v1.5, 768d. They are cached in an `embeddings` table
keyed by (subject_kind, subject_id); unchanged text is never re-embedded.
"""

import hashlib
import json
import math
import struct
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
        vecs = _request_embeddings([t for _, t in missing])
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
        "SELECT p.id, p.path, p.title, v.body_md FROM pages p"
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
    q_vec = cached_embeddings(conn, "query", [(_query_key(query), query)])[_query_key(query)]

    fts_ranks = _fts_page_ranks(conn, query, limit=max(k, 10))
    fts_bonus = {pid: 1.0 / (i + 1) for i, pid in enumerate(fts_ranks)}

    results = []
    for f in facts:
        vec = fact_vecs.get(str(f["id"]))
        if vec is None:
            continue
        score = _cosine(q_vec, vec) + 0.25 * fts_bonus.get(f["page_id"], 0.0)
        results.append({"kind": "fact", "id": f["id"], "score": round(score, 6),
                        "text": f["text"], "page_id": f["page_id"],
                        "status": f["status"]})
    for p in pages:
        vec = page_vecs.get(str(p["id"]))
        if vec is None:
            continue
        score = _cosine(q_vec, vec) + fts_bonus.get(p["id"], 0.0)
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


def _page_block(page, facts, quote_limit=None):
    """Render one page: header, optional body, active claims with citations."""
    lines = ["## %s (%s)" % (page["title"], page["path"])]
    body = (page["body_md"] or "").strip()
    if body:
        lines.append(body)
    if facts:
        lines.append("### Claims")
        for f in facts:
            quote = f["quote"]
            if quote_limit is not None and len(quote) > quote_limit:
                quote = quote[:quote_limit].rstrip() + "…"
            lines.append("- %s %s" % (f["text"], _citation(f)))
    return "\n".join(lines)


def _render_brief(pages, facts_by_page, quote_limit=None):
    parts = []
    for page in pages:
        block = _page_block(page, facts_by_page.get(page["id"], []), quote_limit)
        if block.strip():
            parts.append(block)
    return "\n\n".join(parts)


def build_brief(conn, brain_id, question, budget_tokens=4000):
    """Assemble the prefix-stable brief. Returns (stable_text, question_text).

    The stable text is the compiled canonical content — page headers, active claims,
    each with a compact `[capture N, span a:b]` citation — and is byte-identical
    across calls for the same brain. The question is deliberately NOT used to select
    or order stable content: question-dependent trimming would change the cached
    prefix per question and defeat TensorFold's per-message-boundary reuse (P9).

    Trimming order when over budget: drop low-ranked pages (fewest eligible facts
    first), then low-ranked facts (newest id first, keeping the earliest canonical
    citation), then shorten quotes. Citations are never dropped.
    """
    pages = _page_texts(conn, brain_id)
    facts = eligible_facts(conn, brain_id)
    facts_by_page = {}
    for f in facts:
        facts_by_page.setdefault(f["page_id"], []).append(f)

    def render(pages_list, facts_map, quote_limit=None):
        return _render_brief(pages_list, facts_map, quote_limit)

    stable = render(pages, facts_by_page)
    if _token_estimate(stable) <= budget_tokens:
        return stable, question

    # 1. Drop low-ranked pages: fewest eligible facts first, deterministic tiebreak
    #    on path so the result is reproducible.
    ranked = sorted(pages, key=lambda p: (len(facts_by_page.get(p["id"], [])), p["path"]))
    kept = list(pages)
    for page in ranked:
        if _token_estimate(render(kept, facts_by_page)) <= budget_tokens:
            break
        if len(kept) > 1:
            kept = [p for p in kept if p["id"] != page["id"]]
    stable = render(kept, facts_by_page)

    # 2. Drop low-ranked facts: newest id first (earliest capture stays canonical).
    if _token_estimate(stable) > budget_tokens:
        for page in kept:
            flist = facts_by_page.get(page["id"], [])
            if len(flist) > 1:
                flist_sorted = sorted(flist, key=lambda f: f["id"], reverse=True)
                for f in flist_sorted:
                    if _token_estimate(render(kept, facts_by_page)) <= budget_tokens:
                        break
                    if len(facts_by_page[page["id"]]) > 1:
                        facts_by_page[page["id"]] = [
                            x for x in facts_by_page[page["id"]] if x["id"] != f["id"]]
        stable = render(kept, facts_by_page)

    # 3. Shorten quotes; citations stay.
    for limit in (200, 120, 80, 40):
        if _token_estimate(stable) <= budget_tokens:
            break
        stable = render(kept, facts_by_page, quote_limit=limit)

    return stable, question


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
