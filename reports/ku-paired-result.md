# Knowledge-update experiment (phase 17 Part B): measured result

**LOCAL-JUDGED. Frozen code `028e324`, run head `a84e55a`, budget 600 tokens,
mutation rate 0.2, n=20, complete. Disclosure: the 7,165 s session compiled 7 brains; 13 were
compiled earlier and reused through their sidecars.**

This is the decisive test of the consolidation thesis: for each knowledge-update question, answer
from a pristine brain, run the consolidation pass on a copy, and answer again from the copy. If the
second pass improves answers, consolidation earns its place. It did not.

## Result

| arm | accuracy (n=20) |
|---|---|
| (a) pristine compiled brain | 0.75 |
| (b) consolidated copy | 0.75 |
| (c) keyword retrieval (dataset only) | **0.85** |
| (d) dataset-only arm (B2) | 0.70 |

Paired tests: **(b) vs (a) — 0 gained, 0 lost, McNemar p=1.0.** (b) vs (d) — 4 gained, 3 lost, p=1.0.

Mutations produced by the consolidation pass across all 20 brains:

    questions_mutated_by_consolidation: 0
    policy_halts: 0
    total_superseded: 0
    total_duplicates_linked: 0
    total_flagged: 0

The pass changed nothing, so arms (a) and (b) are the same brain read twice. This is not a failure of
the harness — the provenance sidecars prove arm (a) read an unconsolidated brain while arm (b) read
the copy.

**Corrected by Tes review (t_d67491f3): (b) = (a) was guaranteed by construction.** `compile_all`
already runs `dedupe()` and `supersede_contradictions()`, and `consolidate()` runs the same two
deterministic functions again; it is idempotent on an unchanged brain by design. So the paired
comparison cannot see the pass at work even with perfect update detection — arm (a) would have to be
a brain compiled *without* that pass for the comparison to mean anything. The evidence that the
mechanism misses updates is a different number: **0 supersessions at compile time across all 20
brains**. That number is what causes 1-3 explain, and it is the number that matters.

## Why it happened — measured, not guessed

Three causes, each visible in the compiled brains.

**1. Number words are not normalised, so counts never collide.** From `45dc21b6` ("How many of Emma's
recipes have I tried out?"), the two facts that carry the update are on the same page (`people/emma`):

    The user has tried two of Emma's recipes     (2023-05-29)  key: user tried two emma recipe from emma channel
    The user has tried 3 of Emma's recipes       (2023-05-30)  key: user tried emma recipe   value: ('3',)

"two" is a word, so it stays in the key; "3" is a digit, so it becomes a value. The two facts never
meet, and the stale "two" stays active. The same pattern appears in `4b24c848` ("bought three tops",
then a later count) and `5c40ec5b` ("met up twice").

**2. One entity is split across pages.** For the same user the compiler routes claims to
`decisions/user`, `misc/user`, `misc/the-user`, `people/user` and `people/the-user`. Contradiction
comparison is page-scoped (F1, accepted after review 5), so an update that moves a fact from
`misc/user` to `people/user` is invisible. Measured on the first brain: 355 active facts across 96
pages, with only 3 slot keys shared across pages.

**3. Residual keys are whole-clause strings.** 352 distinct slot keys for 355 facts in that brain:
almost every fact keys on its own phrasing. Only the categorical slots (relationship status,
occupation, location) ever collide, and knowledge-update questions are overwhelmingly counts,
quantities, positions and frequencies — none of which are categorical slots.

So the honest statement is: **consolidation, as implemented, is a no-op on LongMemEval
knowledge-update haystacks.** The thesis is not disproved — it is untested, because the pass has no
mechanism to detect the updates it is meant to resolve.

## Footnote: keyword retrieval on these questions

Arm (c) was right on 2 questions where arm (a) was wrong (`d7c942c3`, `e61a7584`) and never the
reverse: exact p=0.5, which is the smallest p two discordant pairs can produce. At n=20 this is
uninformative, not a direction. `e61a7584` ("How long have I had my cat Luna?", gold 9 months) is
worth naming as a case study: the stale 6-month fact stayed active because the two facts differ in
subject and verb ("Luna has been with her owner" vs "the user has had Luna"), which no proposed fix
catches. Extraction also mislabels Luna as a dog and merges two different Alexes on `people/alex`.

## What this means for the product claim

Nothing in this result weakens the auditability claim — 1,640 of 1,640 facts still quote-equal their
cited span, and that was verified independently. But the claim that consolidation *improves
correctness over time* remains unproven, and must not appear in the README as though it were
measured.

## Recommended next phase (not started)

Make update detection work, then re-run this same experiment unchanged:

1. **Normalise number words to digits** before keying ("two" -> 2), so a count is a value in both
   phrasings.
2. **Give counts an attribute slot** — subject, verb and object head, with the number as the value —
   instead of a whole-clause residual key.
3. **Compare within an entity, not a page.** This reverses part of F1, so it needs care: entity scope
   must not re-admit the false pairs that page scope removed (`projects/alpha` vs `projects/beta`).
   The rule should be: same entity, same attribute, different value.

Then re-run `ku_paired.py` with the same ids config, budget and rate, and compare like with like.

## What was NOT verified

- Only 20 of the 74 eligible knowledge-update questions were run, as the frozen config specifies.
- The judge is local and its label is recorded per question; no human adjudication of the 20 answers.
- No embeddings: the arm comparison is lexical-plus-compiled only.
- The (c) vs (a) gap (0.85 vs 0.75, 2 questions) is not significant at n=20 and is reported as a
  direction, not a claim.
