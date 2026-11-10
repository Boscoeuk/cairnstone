"""Phase 16: does a consolidation pass make compiled memory more correct?

The product's thesis is that a nightly consolidation pass improves a memory over
time. This is the first test of that thesis, paired on the same brains:

  for each knowledge-update question
    1. compile the haystack into a brain
    2. answer BEFORE any consolidation (the brief as the compiler left it)
    3. run the model-free consolidation pass
    4. answer AFTER, from the same brain
    5. judge both answers against gold

A knowledge-update question is exactly the shape consolidation targets: an earlier
value is stated, then a later session updates it. If consolidation works, the
before-answer should serve the stale value and the after-answer the current one.

Deterministic selection, local endpoints only, no cloud. Usage:

  PYTHONPATH=src:. python3 eval/longmemeval/ku_paired.py \
      --questions 20 --budget 600 --seed 20261106
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "eval"))
sys.path.insert(0, str(REPO / "eval" / "longmemeval"))

import harness  # noqa: E402
import lme_eval as lme  # noqa: E402
from cairnstone import compile as cairn_compile  # noqa: E402
from cairnstone import retrieve, store  # noqa: E402
from cairnstone.llm import LLMClient  # noqa: E402

KU_DB_DIR = REPO / "eval" / "results" / "ku-db"
RESULTS_DIR = REPO / "eval" / "results"


def select_knowledge_update(pool, n, seed):
    """Deterministic sample of knowledge-update questions, in dataset order."""
    ku = [q for q in pool if q.get("question_type") == "knowledge-update"]
    rng = random.Random(seed)
    picked = rng.sample(ku, min(n, len(ku)))
    picked.sort(key=lambda q: q["question_id"])
    return picked


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p for discordant counts b and c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    # P(X <= k) for X ~ Binomial(n, 0.5), doubled for a two-sided test.
    tail = sum(_binom(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def _binom(n, k):
    out = 1
    for i in range(k):
        out = out * (n - i) // (i + 1)
    return out


def run_one(question, budget, client):
    qid = question["question_id"]
    db_path = KU_DB_DIR / ("%s.db" % qid)
    conn, brain_id, summary = lme.compile_question(question, db_path, client, True)
    comp = lme.compile_report(summary) if summary else {}

    row = {
        "question_id": qid,
        "question": question["question"],
        "gold": question["answer"],
        "compile": comp,
        "answer_session_ids": question.get("answer_session_ids", []),
    }

    # ---- before: no consolidation has run on this brain
    before = lme.cairnstone_backend(conn, brain_id, question, budget)
    ok_b, amb_b = harness.judge(question["question"], question["answer"],
                                before["answer"], model=lme.JUDGE_MODEL)
    before.update({"correct": ok_b, "judge_ambiguous": amb_b})
    row["before"] = before

    facts_before = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE status = 'active'").fetchone()[0]
    superseded_before = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE status = 'superseded'").fetchone()[0]

    # ---- the intervention: the model-free nightly pass, exactly as cron runs it
    cons = cairn_compile.consolidate(conn, brain_id)
    row["consolidation"] = cons
    facts_after = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE status = 'active'").fetchone()[0]
    row["facts"] = {"active_before": facts_before, "active_after": facts_after,
                    "superseded_before": superseded_before,
                    "superseded_after": conn.execute(
                        "SELECT COUNT(*) FROM facts WHERE status = 'superseded'"
                    ).fetchone()[0]}

    # ---- after: same brain, consolidated
    after = lme.cairnstone_backend(conn, brain_id, question, budget)
    ok_a, amb_a = harness.judge(question["question"], question["answer"],
                                after["answer"], model=lme.JUDGE_MODEL)
    after.update({"correct": ok_a, "judge_ambiguous": amb_a})
    row["after"] = after

    conn.close()
    print("%s before=%s after=%s cons=%s facts=%d->%d brief=%dt->%dt"
          % (qid, "OK" if ok_b else "MISS", "OK" if ok_a else "MISS",
             cons, facts_before, facts_after,
             before["brief_tokens"], after["brief_tokens"]), flush=True)
    return row


def aggregate(rows):
    """Paired counts and the honest summary statistics."""
    b = sum(1 for r in rows if not r["before"]["correct"] and r["after"]["correct"])
    c = sum(1 for r in rows if r["before"]["correct"] and not r["after"]["correct"])
    both_ok = sum(1 for r in rows if r["before"]["correct"] and r["after"]["correct"])
    both_bad = sum(1 for r in rows if not r["before"]["correct"] and not r["after"]["correct"])
    mutated = [r for r in rows if r["consolidation"]["superseded"]
               or r["consolidation"]["duplicates_linked"]]
    return {
        "label": "LOCAL-JUDGED",
        "n": len(rows),
        "before_accuracy": round(sum(1 for r in rows if r["before"]["correct"]) / len(rows), 3),
        "after_accuracy": round(sum(1 for r in rows if r["after"]["correct"]) / len(rows), 3),
        "gained": b, "lost": c, "both_correct": both_ok, "both_wrong": both_bad,
        "mcnemar_exact_p": round(mcnemar_exact(b, c), 4),
        "questions_mutated_by_consolidation": len(mutated),
        "total_superseded": sum(r["consolidation"]["superseded"] for r in rows),
        "total_duplicates_linked": sum(r["consolidation"]["duplicates_linked"] for r in rows),
        "total_flagged": sum(r["consolidation"]["flagged"] for r in rows),
        "mean_brief_tokens_before": round(
            sum(r["before"]["brief_tokens"] for r in rows) / len(rows), 1),
        "mean_brief_tokens_after": round(
            sum(r["after"]["brief_tokens"] for r in rows) / len(rows), 1),
        "judge_ambiguous_count": sum(r[b]["judge_ambiguous"] for r in rows
                                     for b in ("before", "after")),
    }


def main():
    ap = argparse.ArgumentParser(description="Phase 16 paired consolidation test")
    ap.add_argument("--questions", type=int, default=20)
    ap.add_argument("--budget", type=int, default=600)
    ap.add_argument("--seed", type=int, default=20261106)
    ap.add_argument("--split", choices=["s", "oracle"], default="s")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    pool = json.load(open(lme.DATASETS[args.split]))
    picked = select_knowledge_update(pool, args.questions, args.seed)
    print("selected %d knowledge-update questions (seed %d)" % (len(picked), args.seed),
          flush=True)

    client = LLMClient(base_url=lme.ANSWER_BASE_URL, model=lme.ANSWER_MODEL)
    lme._client = client
    harness.JUDGE_URL = lme.JUDGE_URL.rstrip("/") + "/chat/completions"
    harness.JUDGE_MODEL = lme.JUDGE_MODEL

    rows = []
    t0 = time.monotonic()
    for i, q in enumerate(picked, 1):
        print("[%d/%d] %s" % (i, len(picked), q["question_id"]), flush=True)
        rows.append(run_one(q, args.budget, client))

    agg = aggregate(rows)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    out = Path(args.out) if args.out else RESULTS_DIR / (
        "ku-paired-b%d-q%d-%s.json" % (args.budget, len(rows), stamp))
    json.dump({"aggregate": agg, "rows": rows, "elapsed_s": round(time.monotonic() - t0, 1)},
              open(out, "w"), indent=1)
    print("\n" + json.dumps(agg, indent=1))
    print("wrote %s" % out)
    print("elapsed %.1f s" % (time.monotonic() - t0))


if __name__ == "__main__":
    main()
