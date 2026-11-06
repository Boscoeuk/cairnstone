"""Independent adjudication of the dogfood answers.

The local judge and my own reading disagreed on 5 of 40 verdicts. Since I wrote the questions,
my adjudication is not independent either. This script asks a fresh model instance with no
project context to grade each answer against its gold answer, one question at a time, and
records the verdicts so all three readings can be compared.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from cairnstone.llm import LLMClient  # noqa: E402

SYSTEM = ("You are grading answers to questions about a software project. For each item you get "
          "a question, a reference answer, and a candidate answer. Decide whether the candidate "
          "conveys the reference answer. Reply with exactly one word: CORRECT or INCORRECT. "
          "Be strict about numbers and names: a different number is INCORRECT.")

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    results = json.load(open(os.path.join(HERE, "results.json")))
    client = LLMClient()
    out = {"memory": {}, "baseline": {}}
    for r in results["rows"]:
        for side, key in (("memory", "memory_answer"), ("baseline", "baseline_answer")):
            prompt = ("Question: %s\nReference answer: %s\nCandidate answer: %s\n\nVerdict:"
                      % (r["question"], r["gold"], r[key]))
            verdict = client.chat([{"role": "system", "content": SYSTEM},
                                   {"role": "user", "content": prompt}],
                                  model="local-judge", max_tokens=8)
            v = (verdict or "").strip().upper().startswith("CORRECT")
            out[side][r["id"]] = v
            print("%s %-8s %s" % (r["id"], side, "CORRECT" if v else "INCORRECT"), flush=True)
    json.dump(out, open(os.path.join(HERE, "adjudication.json"), "w"), indent=2)
    for side in out:
        print("%s: %d/%d" % (side, sum(out[side].values()), len(out[side])))


if __name__ == "__main__":
    main()
