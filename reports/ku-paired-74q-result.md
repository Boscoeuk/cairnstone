# Knowledge-update experiment, phase 18 (n=74): measured result and verdict

**LOCAL-JUDGED. Frozen code `63521eb`, run head `e424007`, budget 600 tokens, mutation rate 0.2,
n=74, complete, 140,378 s.** Arm (a) was compiled WITHOUT the dedupe/supersede pass; arm (b) is the
consolidated copy of that brain. This is the first version of the experiment in which the pass had
anything to do — the phase 17 run made (b) = (a) by construction.

## Result

| arm | accuracy (n=74) |
|---|---|
| (a) unconsolidated compiled brain | **0.811** (60/74) |
| (b) after the consolidation pass | 0.797 (59/74) |
| (c) keyword retrieval | 0.770 (57/74) |
| (d) dataset-only (relevance + recency) | 0.703 (52/74) |

Paired exact McNemar:

| comparison | gained / lost | p |
|---|---|---|
| (b) vs (a) — the thesis | **1 / 2** | 1.0 |
| (a) vs (d) — compiled vs dataset-only | 7 / 15 | 0.134 |
| (b) vs (d) | 9 / 16 | 0.230 |
| (a) vs (c) — compiled vs keyword | 3 / 6 | 0.508 |

The pass produced, across 74 brains: **15 supersessions, 75 flags, 406 duplicate links, 0 policy
halts.** It ran on 73 of 74 questions.

**Verdict: consolidation does not measurably improve correctness.** (b) is one question better and two
worse than (a). At n=74 that is nothing.

## Why — measured at the mechanism, not inferred

The run's own mechanism metric was broken: it substring-checked `arm["brief"]`, but
`cairnstone_backend` does not return the brief text, so it recorded 0/0 by construction. I recomputed
it exactly (`eval/ku_mechanism.py`): both briefs rebuilt from the frozen brains with
`retrieve.build_brief` — deterministic, no model calls — and each retired fact checked for actual
selection into the brief.

    stale facts retired:                     15
    selected into arm (a)'s brief:           10   (10 questions)
    selected into arm (b)'s brief:            0

So the mechanism works as designed: it removes the stale fact from the brief in 10 of the 15 cases
where it would otherwise be there. And the reason that changes no answers is visible in the same
measurement:

    in all 10 of those questions, the CORRECT newer fact was ALSO in arm (a)'s brief.

The answerer was already holding both the stale and the updated fact, in chronological order, and
resolving in favour of the newer one. Removing the stale copy leaves the answer unchanged. Consolidation
is therefore **real but not the binding constraint**: selection plus recency ordering already carries
the update.

## Hand-check of every pair (Tes review t_e75489ef, condition 2)

All 15 supersessions were read against the corpus. 13 are defensible updates (Dr Smith frequency, Emma
recipe count, H&M tops, to-watch list 20->25, yoga frequency, MCU films 4->5, Luna 6->9 months, eggs
30->20 dozen, three rescheduled dates, an age correction).

- **1 is a clear false positive**: "The user wears their black Adidas sneakers almost every day and
  finds them comfortable" was retired in favour of "The user runs 3 times a week". Different claims;
  the frequency slot collapses both onto the user.
- **1 is ambiguous**: "went to Walmart on 2023-06-03" retired by "went to Walmart on 2023-07-08" —
  these may be two separate visits.

That is the known `cat:qty:<subject>:<subject>:<unit>` defect Tes found on `f0853d11`, and it survives
into the run corpus at roughly 1 in 15 retirements.

## What the run does support

- Compiled memory beats the dataset-only baseline on these questions: 7 gained against 15 lost,
  p=0.134. Not significant at n=74, but it is the largest effect in the experiment and it is in the
  right direction for the product's core claim.
- Compiled memory beats keyword retrieval: 3 vs 6, p=0.508. Parity, as before.
- The pass is safe at scale: 0 halts, 406 duplicate links, and 13 of 15 retirements defensible.

## What it does not support

The claim that nightly consolidation **improves correctness over time**. It should not appear in the
README. Consolidation remains defensible as *hygiene* — it removes stale facts from the brain and
therefore from future briefs, which matters for auditability and for keeping one live value per
attribute — but it is not where the accuracy comes from.

## What was NOT verified

- The judge is local and every verdict is labelled LOCAL-JUDGED; no human adjudication of 74 answers.
- The 75 flags were not individually hand-checked (the 15 retirements were).
- Retrieval scoring, the brief format and the answer prompt were not tuned in this phase; only the
  compiler and the harness changed.
- The LoCoMo 150-question and LongMemEval S-20 re-measure is still parked; README figures remain stale
  until it runs at this HEAD.
