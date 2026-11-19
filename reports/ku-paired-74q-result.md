# Knowledge-update experiment, phase 18 (n=74): measured result and verdict

**LOCAL-JUDGED.** Answerer: `glm-5.3-flash` on the local engine (port 8460, `owned_by=tensorfold`,
context 262144), confirmed live at `/health` and `/v1/models`. Judge: the spark-side DeepSeek-V4.1-Flash
route (port 8889), scrubbed in the artifact to `spark-side-model`. Frozen code `63521eb`, run head
`e424007`, budget 600 tokens, mutation rate 0.2, n=74, complete, 140,378 s, 0 policy halts. Artifact:
`eval/results/ku-paired-74q.json`.

Arm (a) was compiled WITHOUT the dedupe/supersede pass; arm (b) is the consolidated copy of that brain.
This is the first version of the experiment in which the pass had anything to do — the phase 17 run made
(b) = (a) by construction.

## Result

| arm | accuracy (n=74) |
|---|---|
| (a) unconsolidated compiled brain | **0.811** (60/74) |
| (b) after the consolidation pass | 0.797 (59/74) |
| (c) keyword retrieval | 0.770 (57/74) |
| (d) dataset-only (relevance + recency) | 0.703 (52/74) |

Paired exact McNemar. Columns are stated from the first arm's point of view — "wins" means the first
arm answered correctly where the second did not:

| comparison | first arm wins / loses | p |
|---|---|---|
| (b) vs (a) — the thesis | b wins 1, loses 2 | 1.0 |
| (a) vs (d) — compiled vs dataset-only | **a wins 15, loses 7** | 0.134 |
| (b) vs (d) | b wins 16, loses 9 | 0.230 |
| (a) vs (c) — compiled vs keyword | a wins 6, loses 3 | 0.508 |

The pass produced, across 74 brains: **15 supersessions, 75 flags, 406 duplicate links, 0 policy
halts**, and changed 73 of the 74 brains (`031748ae_abs` produced nothing).

**Verdict: consolidation does not measurably improve correctness.** (b) is one question better and two
worse than (a). At n=74 that is nothing.

## Why — measured at the mechanism, not inferred

The run's own mechanism metric was broken: it substring-checked `arm["brief"]`, but
`cairnstone_backend` does not return the brief text, so it recorded 0/0 by construction. I recomputed
it exactly (`eval/ku_mechanism.py`): both briefs rebuilt from the frozen brains with
`retrieve.build_brief` and each retired fact checked for actual selection into the brief. The rebuild
uses no LLM calls; embeddings are read from the brain's own cache. Tes reproduced it independently and
confirmed all 74 brain hashes match the run's records.

    stale facts retired:                     15
    selected into arm (a)'s brief:           10   (10 questions)
    selected into arm (b)'s brief:            0
    the correct newer fact in arm (a):       10   (all 10 of those questions)

At the **record layer** the pass works: it removes the stale record in 10 of the 15 cases where it
would otherwise be selected, and the newer record was already present alongside it in every one.

**But it is neither harmless nor the binding constraint.** The two questions where (b) lost are
`2698e78f` and `2698e78f_abs`, both inside those 10. Diffing the briefs:

- arm (a) carried the stale record, the newer record **and** the contradiction note pointing at the
  newer value ("Earlier: … every two weeks (contradicts The user sees Dr Smith every week)"); it
  answered "Every week", correctly.
- arm (b) lost the stale record **and the note with it**, because the note hung off the retired fact.
  It answered "Every two weeks", wrongly.

So retiring a stale record also deletes the pointer to its replacement. At text level the stale claim
survives in arm (b)'s brief in 2 of 15 cases (both inside supporting quotes), which consolidation does
not touch — "removes the stale fact from the brief" is true of the Records block only.

The single gain is not a supersession effect: `ba61f0b9` had 0 supersessions and 0 flags, only 5
duplicate links. The paired effect decomposes as **dedupe +1 / supersession 0 gained, 2 lost**.

Whether recency ordering alone would carry the update in arm (a) **remains unmeasured**: no arm
isolates ordering without the contradiction note, and the two losses are exactly the cases where the
note was removed. That is a hypothesis, not a finding.

## Hand-check of every pair (Tes review t_e75489ef, condition 2)

All 15 supersessions were read against the corpus, with capture dates, session dates, question, gold
and both arms' answers. Tes checked my calls independently.

13 are defensible updates: Dr Smith frequency (×2, the designed B3 pair), Emma recipes 2->3, to-watch
20->25, yoga twice->three times, MCU films 4->5, Luna 6->9 months, eggs 30->20 dozen, three rescheduled
dates, H&M three->five tops.

- **1 clear false positive**: "wears their black Adidas sneakers almost every day" retired in favour of
  "runs 3 times a week". Different attributes on the same entity, retired with no flag. This is the
  `cat:qty:<subject>:<subject>:<unit>` defect Tes predicted, and it survives into the run corpus at
  roughly 1 in 15 retirements.
- **1 benign duplicate, not two visits**: the two Walmart haystack sessions are byte-identical
  (5,767 characters, dated 2023-06-10 and 2023-07-10). One visit recorded twice; newest-wins is
  arguably correct here.
- **1 dataset self-contradiction**: `a1eacc2a` is "I'm 32" (2023-05-05) retired by "I'm 30"
  (2023-05-30). Recency happens to be wrong; the question does not depend on it and both arms are
  wrong anyway. It is the cleanest example of the pass trusting order over content.

## What the run does support

- Compiled memory beats the dataset-only baseline: (a) wins 15, loses 7, p=0.134. Not significant at
  n=74, but it is the largest effect in the experiment and points the right way for the product's core
  claim. It is answerer-dependent, so it must be re-checked whenever the answerer model changes.
- Compiled memory is at parity with keyword retrieval: (a) wins 6, loses 3, p=0.508.
- The pass is safe at scale: 0 halts, 406 duplicate links, 13 of 15 retirements defensible.

## What it does not support

The claim that nightly consolidation **improves correctness over time**. It should not appear in the
README as an accuracy claim. Consolidation remains defensible as *hygiene* — one live value per
attribute, stale records gone from future briefs, which is what auditability needs — but it is not
where the accuracy comes from.

## Caveats

- The judge is local; every verdict is LOCAL-JUDGED and no human adjudicated the 74 answers.
- The 75 flags were not individually hand-checked (the 15 retirements were).
- The artifact was scrubbed for publish-guard, inside `judge_identity` only: the judge's name became
  `spark-side-model` and its derivative marker was shortened to `SPARK=1`. No substantive field
  changed (every number recomputes from the rows). Consequence: the artifact no longer names the
  specific model derivative the judge runs on; the image and recipe string pin it, but a reader cannot
  tell from the name alone.
- Retrieval scoring, the brief format and the answer prompt were not tuned in this phase; only the
  compiler and the harness changed.
- The LoCoMo 150-question and LongMemEval S-20 re-measure is still parked; README figures remain stale
  until it runs at this HEAD.
