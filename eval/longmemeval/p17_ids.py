"""Print the phase-17 eligible KU ids and the pre-registered pilot subset.

Dataset-only, no model calls. Sampling procedure is the one pre-registered in
docs/phase17-brief.md: eligible list sorted by question_id, then
random.Random(seed).sample, then sorted again by question_id.
"""

import json
import random
import sys

data = json.load(open("eval/datasets/longmemeval_s_cleaned.json"))
ku = [q for q in data if q.get("question_type") == "knowledge-update"]
excl = {"08e075c7", "0f05491a", "2133c1b5_abs", "71315a70"}
eligible = sorted((q for q in ku if q["question_id"] not in excl),
                  key=lambda q: q["question_id"])
pilot = sorted(q["question_id"] for q in random.Random(20261110).sample(eligible, 20))

print("eligible %d" % len(eligible))
print("ALL74 " + json.dumps([q["question_id"] for q in eligible]))
print("PILOT20 " + json.dumps(pilot))
sys.exit(0)
