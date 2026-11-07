"""Phase 13: LongMemEval evaluation for Cairnstone.

Runs the compiled-memory backend (cairnstone), a keyword-search baseline, and an
optional full-context baseline over LongMemEval questions, judging every answer
with the same local judge and verdict parsing as the LoCoMo harness
(eval/harness.py). All endpoints are local; no cloud.

Usage:
  PYTHONPATH=src:. python3 eval/longmemeval/lme_eval.py \
      --split s --questions 20 --budget 600 --seed 20261106
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "eval"))

from cairnstone import compile as cairn_compile  # noqa: E402
from cairnstone import retrieve, store  # noqa: E402
from cairnstone.llm import LLMClient  # noqa: E402
import harness  # noqa: E402  (reuses its judge + verdict parsing verbatim)

# Phase-13 endpoints (rules): local only. Env-overridable.
ANSWER_BASE_URL = os.environ.get("CAIRNSTONE_BASE_URL", "http://127.0.0.1:8460/v1")
ANSWER_MODEL = os.environ.get("CAIRNSTONE_MODEL", "glm-5.3-flash")
JUDGE_URL = os.environ.get("CAIRN_JUDGE_URL", "http://127.0.0.1:8000/v1")
JUDGE_MODEL = os.environ.get("CAIRN_JUDGE_MODEL", "local-judge")

# The judge endpoint/model differ from the LoCoMo harness defaults; point the
# imported harness at the phase-13 judge before any judging happens, so the
# prompt and verdict parsing stay byte-identical to eval/harness.py.
harness.JUDGE_URL = JUDGE_URL.rstrip("/") + "/chat/completions"
harness.JUDGE_MODEL = JUDGE_MODEL

DATASETS = {
    "s": REPO / "eval" / "datasets" / "longmemeval_s_cleaned.json",
    "oracle": REPO / "eval" / "datasets" / "longmemeval_oracle.json",
}
DB_DIR = REPO / "eval" / "results" / "lme-db"
RESULTS_DIR = REPO / "eval" / "results"
TYPES = ["multi-session", "temporal-reasoning", "knowledge-update",
         "single-session-user", "single-session-assistant",
         "single-session-preference"]
MAX_SESSION_CHARS = 3000          # split longer sessions at turn boundaries
CONTEXT_WINDOW_TOKENS = 262144    # answer endpoint model window
CONTEXT_SAFETY_TOKENS = 8000      # headroom for the reply and template overhead

# The terse answering instruction, reused verbatim from eval/dogfood/dogfood_eval.py
# so results are comparable across phases.
ANSWER_SUFFIX = ("\n\nReply with a short answer only - a date, name, number, place, short phrase, "
                 "or a short list when the question asks for one. No preamble.")

STOP = set("""a an the and or of in on at to for from by with about as is are was were be been being
do does did doing has have had what which who whom whose when where why how many much i me my we
our you your he she it they them their his her its this that these those will would can could
should shall may might must not no nor so than too very s t""".split())


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP]


# ------------------------------------------------------------------ selection
def select_questions(pool: list[dict], n: int, seed: int) -> list[dict]:
    """Deterministic, seeded, stratified selection: proportional to the type
    distribution, at least 2 per type, remainder by largest remainder."""
    by_type: dict[str, list[dict]] = {}
    for q in pool:
        by_type.setdefault(q["question_type"], []).append(q)
    for qs in by_type.values():
        qs.sort(key=lambda q: q["question_id"])  # stable order before sampling

    total = len(pool)
    raw = {t: n * len(by_type.get(t, [])) / total for t in by_type}
    # The "at least 2 per type" floor only applies when the request can satisfy
    # it (n >= 2 types); a 2-question smoke run would otherwise balloon to 12.
    floor = 2 if n >= 2 * len(by_type) else 0
    alloc = {t: max(floor, int(raw[t])) for t in by_type}
    # Largest-remainder pass over the unmet share.
    short = n - sum(alloc.values())
    order = sorted(by_type, key=lambda t: raw[t] - int(raw[t]), reverse=True)
    i = 0
    while short > 0:
        alloc[order[i % len(order)]] += 1
        short -= 1
        i += 1
    while short < 0:  # min-2 floor overshot the request on tiny runs
        for t in sorted(by_type, key=lambda t: alloc[t], reverse=True):
            if alloc[t] > floor:
                alloc[t] -= 1
                short += 1
                if short == 0:
                    break
        else:
            break

    rng = random.Random(seed)
    chosen: list[dict] = []
    for t in sorted(by_type):
        k = min(alloc[t], len(by_type[t]))
        chosen.extend(rng.sample(by_type[t], k))
    return chosen


# ------------------------------------------------------------ capture building
def session_chunks(session: list[dict], date: str) -> list[str]:
    """One capture per session, prefixed with the session date so relative dates
    resolve. Sessions longer than MAX_SESSION_CHARS split at turn boundaries into
    multiple captures, each carrying the same date prefix."""
    prefix = f"Session date: {date}"
    body: list[str] = []
    chunks: list[str] = []
    size = 0
    for turn in session:
        line = f"{turn['role']}: {turn['content']}"
        if body and size + len(line) > MAX_SESSION_CHARS:
            chunks.append(prefix + "\n" + "\n".join(body))
            body, size = [], 0
        body.append(line)
        size += len(line) + 1
    if body:
        chunks.append(prefix + "\n" + "\n".join(body))
    return chunks


def build_captures(question: dict, conn, brain_id: int | None) -> list[int]:
    """One capture per (chunk of a) haystack session; returns capture ids."""
    ids = []
    for si, (date, session) in enumerate(zip(question["haystack_dates"],
                                             question["haystack_sessions"])):
        for ci, chunk in enumerate(session_chunks(session, date)):
            ref = f"longmemeval:{question['question_id']}:session{si}:chunk{ci}"
            ids.append(store.add_capture(conn, brain_id, "conversation", chunk,
                                         ref, captured_at=date))
    return ids


def compile_question(question: dict, db_path: Path, client: LLMClient,
                     recompile: bool) -> tuple[Any, int, dict]:
    """Build and compile the per-question brain. Returns (conn, brain_id, summary)."""
    if db_path.exists() and not recompile:
        conn = store.init_db(str(db_path))
        brain_id = conn.execute("SELECT id FROM brains ORDER BY id LIMIT 1") \
            .fetchone()["id"]
        return conn, brain_id, {}
    tmp = db_path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = store.init_db(str(tmp))
    ws = store.create_workspace(conn, "default")
    brain_id = store.create_brain(conn, ws, "default", "default")
    capture_ids = build_captures(question, conn, brain_id)
    summary = cairn_compile.compile_all(conn, brain_id, capture_ids, client)
    conn.close()
    tmp.replace(db_path)
    conn = store.init_db(str(db_path))
    return conn, brain_id, summary


def compile_report(summary: dict) -> dict:
    """Per-question compile stats; a reject rate above 0.5 is reported, not fatal."""
    reasons = Counter(reason.split(":")[0] for _, _, reason in summary["facts_rejected"])
    accepted = summary["facts_accepted"]
    rejected = len(summary["facts_rejected"])
    rate = rejected / (accepted + rejected) if (accepted + rejected) else 0.0
    return {
        "captures": summary["captures"],
        "facts_accepted": accepted,
        "facts_rejected": rejected,
        "rejections_by_reason": dict(sorted(reasons.items())),
        "failed_captures": len(summary["failed_captures"]),
        "reject_rate": round(rate, 3),
        "reject_rate_high": rate > 0.5,
        "duplicates_linked": summary["duplicates_linked"],
        "superseded": summary["superseded"],
    }


# ------------------------------------------------------------------- backends
def answer(client: LLMClient, stable: str, volatile: str) -> dict:
    """One answer call. The stable context is its own leading system message so
    TensorFold's prefix cache hits (same layout as the LoCoMo harness)."""
    text = client.chat([{"role": "system", "content": stable},
                        {"role": "user", "content": volatile + ANSWER_SUFFIX}],
                       model=ANSWER_MODEL, max_tokens=120)
    tel = client.telemetry_last()
    return {
        "answer": (text or "").strip(),
        "prompt_tokens": tel.get("prompt_tokens"),
        "latency_s": round(tel.get("elapsed_seconds", 0.0), 3),
    }


def cairnstone_backend(conn, brain_id, question: dict, budget: int) -> dict:
    """Compiled memory: retrieve.build_brief at the requested budget, citations
    rendered, gold_support_in_brief where computable."""
    t0 = time.monotonic()
    stable, volatile, selected = retrieve.build_brief(
        conn, brain_id, question["question"], budget_tokens=budget)
    out = answer(_client, stable, volatile)
    fact_ids = [f["id"] for f in selected]
    citations = retrieve.render_citations(conn, fact_ids)
    return {
        "answer": out["answer"],
        "latency_s": round(time.monotonic() - t0, 3),
        "brief_tokens": (len(stable) + len(volatile)) // 4,
        "prompt_tokens": out["prompt_tokens"],
        "citations_used": volatile.count("[capture "),
        "citations": [c["source_ref"] for c in citations][:20],
        "gold_support_in_brief": retrieve.gold_support_in_brief(
            question["answer"], [f["text"] for f in selected]),
    }


def keyword_backend(question: dict) -> dict:
    """'Just search the raw logs' baseline: top-3 whole sessions by lexical
    overlap with the question, verbatim."""
    q = Counter(tokens(question["question"]))
    scored = []
    for si, (date, session) in enumerate(zip(question["haystack_dates"],
                                             question["haystack_sessions"])):
        text = "\n".join(f"{t['role']}: {t['content']}" for t in session)
        t = Counter(tokens(text))
        overlap = sum(min(q[w], t[w]) for w in q)
        if overlap:
            scored.append((overlap / (1 + math.log(1 + sum(t.values()))), si, text))
    scored.sort(key=lambda x: -x[0])
    top = scored[:3]
    ctx = "\n\n".join(f"Session date: {question['haystack_dates'][si]}\n{text}"
                      for _, si, text in top)
    out = answer(_client,
                 "Answer the question from these session excerpts only.\n\n" + ctx,
                 "Question: " + question["question"])
    return {"answer": out["answer"], "latency_s": out["latency_s"],
            "prompt_tokens": out["prompt_tokens"],
            "sessions_used": [si for _, si, _ in top]}


def full_context_backend(question: dict) -> dict | None:
    """Whole haystack. Never truncates: if the prompt cannot fit the model's
    window the row says so instead of dropping content."""
    parts = [f"Session date: {date}\n" +
             "\n".join(f"{t['role']}: {t['content']}"
                       for t in question["haystack_sessions"][si])
             for si, date in enumerate(question["haystack_dates"])]
    stable = ("You are answering questions about recorded conversations. Use only "
              "the material below.\n\n" + "\n\n".join(parts))
    est_tokens = len(stable) // 4
    if est_tokens + CONTEXT_SAFETY_TOKENS > CONTEXT_WINDOW_TOKENS:
        return {"answer": None, "skipped": "context_window_exceeded",
                "estimated_tokens": est_tokens}
    out = answer(_client, stable, "Question: " + question["question"])
    return {"answer": out["answer"], "latency_s": out["latency_s"],
            "prompt_tokens": out["prompt_tokens"], "estimated_tokens": est_tokens}


# --------------------------------------------------------------------- runner
_client: LLMClient = None  # type: ignore[assignment]


def run_question(question: dict, budget: int, fc: bool, recompile: bool) -> dict:
    global _client
    qid = question["question_id"]
    db_path = DB_DIR / f"{qid}.db"
    conn, brain_id, summary = compile_question(question, db_path, _client, recompile)
    comp = compile_report(summary) if summary else {"cached": True}
    if comp.get("reject_rate_high"):
        print(f"  WARNING {qid}: reject rate {comp['reject_rate']} above 0.5", flush=True)

    row = {"question_id": qid, "question_type": question["question_type"],
           "question": question["question"], "gold": question["answer"],
           "compile": comp, "backends": {}}

    r = cairnstone_backend(conn, brain_id, question, budget)
    ok, amb = harness.judge(question["question"], question["answer"], r["answer"], model=JUDGE_MODEL)
    r.update({"correct": ok, "judge_ambiguous": amb})
    row["backends"]["cairnstone"] = r

    r = keyword_backend(question)
    ok, amb = harness.judge(question["question"], question["answer"], r["answer"], model=JUDGE_MODEL)
    r.update({"correct": ok, "judge_ambiguous": amb})
    row["backends"]["keyword"] = r

    if fc:
        r = full_context_backend(question)
        if r and r.get("answer") is not None:
            ok, amb = harness.judge(question["question"], question["answer"], r["answer"], model=JUDGE_MODEL)
            r.update({"correct": ok, "judge_ambiguous": amb})
        elif r:
            r["correct"] = None
            r["judge_ambiguous"] = False
        row["backends"]["full_context"] = r

    conn.close()
    mem = row["backends"]["cairnstone"]
    print(f"{qid} [{question['question_type']}] cairnstone={'OK' if mem['correct'] else 'MISS'} "
          f"keyword={'OK' if row['backends']['keyword']['correct'] else 'MISS'} "
          f"brief={mem['brief_tokens']}t {mem['latency_s']}s", flush=True)
    return row


def aggregate(rows: list[dict]) -> dict:
    """Accuracy overall and per type, mean tokens, median latency, outlier count.
    An outlier is a cairnstone latency above 3x the median."""
    def acc(rs, backend):
        vals = [r["backends"][backend]["correct"] for r in rs
                if backend in r["backends"]
                and r["backends"][backend].get("correct") is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    lat = sorted(r["backends"]["cairnstone"]["latency_s"] for r in rows)
    med = (lat[len(lat) // 2] if len(lat) % 2 else (lat[len(lat) // 2 - 1]
                                                   + lat[len(lat) // 2]) / 2) if lat else 0
    per_type = {}
    for t in sorted({r["question_type"] for r in rows}):
        rs = [r for r in rows if r["question_type"] == t]
        per_type[t] = {"n": len(rs),
                       "cairnstone_accuracy": acc(rs, "cairnstone"),
                       "keyword_accuracy": acc(rs, "keyword"),
                       "full_context_accuracy": acc(rs, "full_context")}
    toks = [r["backends"]["cairnstone"]["brief_tokens"] for r in rows]
    return {
        "label": "LOCAL-JUDGED",
        "n": len(rows),
        "accuracy_overall": {"cairnstone": acc(rows, "cairnstone"),
                             "keyword": acc(rows, "keyword"),
                             "full_context": acc(rows, "full_context")},
        "accuracy_by_type": per_type,
        "mean_brief_tokens": round(sum(toks) / len(toks), 1) if toks else 0,
        "median_latency_s": round(med, 3),
        "outlier_count": sum(1 for x in lat if med and x > 3 * med),
        "judge_ambiguous_count": sum(r["backends"][b]["judge_ambiguous"]
                                     for r in rows for b in r["backends"]),
    }


def main() -> None:
    global _client
    ap = argparse.ArgumentParser(description="Phase 13 LongMemEval evaluation")
    ap.add_argument("--split", choices=["s", "oracle"], default="s")
    ap.add_argument("--questions", type=int, default=20)
    ap.add_argument("--budget", type=int, default=600)
    ap.add_argument("--seed", type=int, default=20261106)
    ap.add_argument("--full-context-questions", type=int, default=5,
                    help="first K of the selected ids get the full-context baseline")
    ap.add_argument("--recompile", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    _client = LLMClient(base_url=ANSWER_BASE_URL, model=ANSWER_MODEL)
    pool = json.load(open(DATASETS[args.split]))
    selected = select_questions(pool, args.questions, args.seed)
    # Full-context baseline runs on the first K ids in selection order (a fixed,
    # deterministic subset); reported in that same order, not sorted.
    fc_ids = [q["question_id"] for q in selected[:args.full_context_questions]]
    print(f"split={args.split} n={len(selected)} budget={args.budget} "
          f"seed={args.seed} full_context_ids={fc_ids}", flush=True)

    rows = [run_question(q, args.budget, q["question_id"] in fc_ids, args.recompile)
            for q in selected]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    out_path = Path(args.out) if args.out else \
        RESULTS_DIR / f"longmemeval-{args.split}-{args.budget}-{len(rows)}q-{stamp}.json"
    payload = {
        "label": "LOCAL-JUDGED",
        "split": args.split, "budget": args.budget, "seed": args.seed,
        "question_ids": [q["question_id"] for q in selected],
        "full_context_ids": fc_ids,
        "judge": {"url": JUDGE_URL, "model": JUDGE_MODEL},
        "answer_model": ANSWER_MODEL,
        "aggregate": aggregate(rows),
        "rows": rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    agg = payload["aggregate"]
    print(json.dumps(agg, indent=2))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
