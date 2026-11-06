"""Dogfood evaluation: compiled memory vs keyword retrieval over the same raw transcript.

Corpus: this profile's own Hermes session transcript (274 captures, no curated reports).
Both backends answer with the same local model and the same terse instruction. A local judge
scores each answer against a gold answer that is independently known from the project's reports.

The point is not a benchmark number. It is whether compiled, cited memory answers questions about
real work better than keyword search over the same raw material.
"""
import argparse
import json
import math
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from cairnstone import retrieve, store  # noqa: E402
from cairnstone.llm import LLMClient  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ANSWER_SUFFIX = ("\n\nReply with a short answer only - a date, name, number, place, short phrase, "
                 "or a short list when the question asks for one. No preamble.")
JUDGE_SYSTEM = ("You are a strict grader. Compare the candidate answer with the reference answer. "
                "Reply with exactly one word: CORRECT if the candidate conveys the reference, "
                "otherwise INCORRECT. Numbers must match.")

STOP = set("""a an the and or of in on at to for from by with about as is are was were be been being
do does did doing has have had what which who whom whose when where why how many much i me my we
our you your he she it they them their his her its this that these those will would can could
should shall may might must not no nor so than too very s t""".split())


def tokens(text):
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP]


def keyword_retrieve(conn, brain_id, question, k=3):
    """Naive baseline: rank raw captures by content-token overlap. This is what a keyword/FTS
    search over session logs gives you."""
    q = Counter(tokens(question))
    scored = []
    for row in conn.execute("SELECT id, content FROM captures WHERE brain_id = ?", (brain_id,)):
        t = Counter(tokens(row["content"]))
        overlap = sum(min(q[w], t[w]) for w in q)
        if overlap:
            score = overlap / (1 + math.log(1 + sum(t.values())))
            scored.append((score, row["content"]))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:k]]


def judge(client, question, gold, answer, model):
    out = client.chat([
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": "Question: %s\nReference answer: %s\nCandidate answer: %s\n\n"
                                    "Verdict:" % (question, gold, answer)},
    ], model=model, max_tokens=8)
    text = (out or "").strip().upper()
    return text.startswith("CORRECT")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(HERE, "session.db"))
    ap.add_argument("--questions", default=os.path.join(HERE, "questions.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "results.json"))
    ap.add_argument("--budget", type=int, default=600)
    ap.add_argument("--model", default="glm-5.3-flash")
    ap.add_argument("--judge-model", default="local-judge")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    conn = store.init_db(args.db)
    brain = conn.execute("SELECT id FROM brains ORDER BY id LIMIT 1").fetchone()["id"]
    client = LLMClient()
    questions = json.load(open(args.questions))
    if args.limit:
        questions = questions[:args.limit]

    rows = []
    for q in questions:
        # compiled memory
        stable, volatile, selected = retrieve.build_brief(
            conn, brain, q["question"], budget_tokens=args.budget)
        answer = client.chat([{"role": "system", "content": stable},
                              {"role": "user", "content": volatile + ANSWER_SUFFIX}],
                             model=args.model, max_tokens=120)
        citations = retrieve.render_citations(conn, [f["id"] for f in selected])

        # keyword baseline
        chunks = keyword_retrieve(conn, brain, q["question"], k=3)
        ctx = "\n\n".join(chunks)
        base_answer = client.chat([
            {"role": "system", "content": "Answer the question from these session excerpts only.\n\n" + ctx},
            {"role": "user", "content": "Question: " + q["question"] + ANSWER_SUFFIX}],
            model=args.model, max_tokens=120)

        ok_mem = judge(client, q["question"], q["gold"], answer, args.judge_model)
        ok_base = judge(client, q["question"], q["gold"], base_answer, args.judge_model)
        rows.append({"id": q["id"], "question": q["question"], "gold": q["gold"],
                     "known_from": q["known_from"],
                     "memory_answer": answer, "memory_correct": ok_mem,
                     "memory_citations": citations[:600],
                     "baseline_answer": base_answer, "baseline_correct": ok_base,
                     "baseline_chunks": len(chunks)})
        print("%s mem=%s base=%s | %s" % (q["id"], "OK " if ok_mem else "MISS",
                                          "OK " if ok_base else "MISS", q["question"][:60]), flush=True)

    n = len(rows)
    agg = {"n": n,
           "memory_accuracy": sum(r["memory_correct"] for r in rows) / n,
           "baseline_accuracy": sum(r["baseline_correct"] for r in rows) / n}
    json.dump({"aggregate": agg, "rows": rows}, open(args.out, "w"), indent=2)
    print("\ncompiled memory: %.1f%% (%d/%d)" % (100 * agg["memory_accuracy"],
                                                 sum(r["memory_correct"] for r in rows), n))
    print("keyword search : %.1f%% (%d/%d)" % (100 * agg["baseline_accuracy"],
                                               sum(r["baseline_correct"] for r in rows), n))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
