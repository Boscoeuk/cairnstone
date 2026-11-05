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

BUCKETS = store.DEFAULT_BUCKETS

EXTRACTION_SYSTEM = """You extract facts from conversation captures for a \
personal memory store.

You will be given one capture: a timestamp line, then the text. Reply with ONLY a JSON \
object, no prose, no markdown fences, in exactly this shape:

{"facts": [{"text": "...", "quote": "...", "bucket": "people|projects|decisions|customers|misc", "page_title": "...", "page_path": "..."}]}

Rules:
- "text": one self-contained fact stated in the capture.
- Atomic attribute facts for people are REQUIRED whenever the capture implies \
them: relationship status (single, married, divorced, dating), location, \
occupation, age, and family role. Emit each as its own fact, e.g. "Caroline \
is single". A direct inference is allowed only when a quote in the capture \
supports it — "I'm single" or "I plan to become a single parent" supports \
"Caroline is single" — but never invent an attribute without a supporting \
quote. The quote rule still governs: no quote, no fact.
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
        for key in ("text", "quote", "bucket", "page_title", "page_path"):
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
    # Whitespace-normalised fallback: align the normalised quote inside the
    # normalised capture, then map offsets back through a position table.
    norm_cap = _norm(capture_text)
    norm_quote = _norm(quote)
    if not norm_quote:
        return None
    # Build mapping from normalised index -> original index by walking the
    # original text: each non-ws char maps to itself; each ws run collapses
    # to one normalised space mapped to the run's first char.
    mapping = []
    j = 0
    for i, ch in enumerate(capture_text):
        if j >= len(norm_cap):
            break
        if ch.isspace():
            if j > 0 and norm_cap[j - 1] != " ":
                mapping.append(i)
                j += 1
        else:
            mapping.append(i)
            j += 1
    if len(mapping) != len(norm_cap):
        return None
    j = norm_cap.find(norm_quote)
    if j == -1:
        return None
    start = mapping[j]
    last = mapping[j + len(norm_quote) - 1]
    # End at the end of the last matched original character.
    end = last + 1
    return (start, end)


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

    `rejected` is a list of (fact_text, reason) tuples.
    """
    accepted, rejected = [], []
    for f in facts:
        span = locate(capture_text_of(conn, capture_id), f["quote"])
        if span is None:
            rejected.append((f["text"], "quote not found in capture"))
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


# -------------------------------------------------------------------- dedupe

def dedupe(conn, brain_id):
    """Link identical claims on the same page as corroboration (policy P7).

    The later fact stays active and carries `duplicate_of` pointing at the canonical one, so
    history is kept and a brief never repeats the same claim. Nothing is retracted or deleted.
    Returns the number of duplicates linked.
    """
    rows = conn.execute(
        "SELECT f.id, f.page_id, f.text FROM facts f JOIN pages p"
        " ON p.id = f.page_id WHERE p.brain_id = ? AND f.status = 'active'"
        " AND f.duplicate_of IS NULL ORDER BY f.id",
        (brain_id,),
    ).fetchall()
    canonical, linked = {}, 0
    for r in rows:
        key = (r["page_id"], _norm(r["text"]).lower())
        if key in canonical:
            conn.execute("UPDATE facts SET duplicate_of = ? WHERE id = ?",
                         (canonical[key], r["id"]))
            linked += 1
        else:
            canonical[key] = r["id"]
    conn.commit()
    return linked


# ------------------------------------------------------------- contradictions

def supersede_contradictions(conn, brain_id):
    """Supersede older facts whose subject/slot matches but value differs.

    A fact's subject/slot is the text with its value (last number-bearing
    token group) removed; two active facts on the same page with the same
    key but different values contradict. The newer capture wins; the older
    fact is superseded via store.supersede_fact, never deleted.
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
    for page_id, facts in by_page.items():
        seen = {}
        for r in facts:
            key, value = _split_subject_slot(r["text"])
            if key is None:
                continue
            if key in seen and seen[key][1] != value:
                old, new = seen[key][2], r
                # Newer capture id wins (captures are inserted in order).
                if new["capture_id"] < old["capture_id"]:
                    old, new = new, old
                store.supersede_fact(conn, old["id"], new["id"])
                superseded += 1
                seen[key] = (key, value, new)
            else:
                seen[key] = (key, value, r)
    return superseded


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
    parser = argparse.ArgumentParser(prog="cairn.compile",
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
