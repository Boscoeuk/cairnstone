# Phase 18 brief — make consolidation able to detect a knowledge update

**Owner:** Polly (project manager). **Implementer:** local OMP worker. **Independent reviewer:** Tes.
**Baseline evidence:** `reports/ku-paired-result.md` (n=20, arms a 0.75 / b 0.75, zero mutations) and
`reports/tes-review-5.md`.

## Why this phase exists

The knowledge-update experiment returned a no-op: the consolidation pass mutated nothing on 20
LongMemEval knowledge-update haystacks, so arms (a) and (b) were the same brain. Three causes were
measured:

1. **Number words are not normalised.** "tried two of Emma's recipes" keys as
   `user tried two emma recipe from emma channel`; "tried 3 of Emma's recipes" keys as
   `user tried emma recipe` with value `3`. Same page, same claim, different keys, no supersession.
2. **One entity is split across pages** (`decisions/user`, `misc/user`, `misc/the-user`,
   `people/user`, `people/the-user`) and comparison is page-scoped (F1), so cross-page updates are
   invisible.
3. **Residual keys are whole-clause strings** (352 keys for 355 facts in one brain), so paraphrases
   never collide; only categorical slots (relationship, occupation, location) ever do.

Phase 18 fixes those three things and nothing else. It must not touch retrieval, the brief format,
the answer prompt, the judge, or the eval harness.

## D1 — normalise number words before slot keying

In `_norm` (or immediately before `_split_subject_slot` keys), map number words to digits:
`zero..twenty`, `thirty, forty, fifty, sixty, seventy, eighty, ninety`, `hundred`, `thousand`, and
simple compounds ("twenty five" -> 25, "three hundred" -> 300). Also `a couple` -> 2, `a dozen` -> 12.
Leave ordinals (`first`, `second`, `third`) and "one of" alone — "one of Emma's recipes" is a count of
1 and normalises correctly.

Scope: normalisation applies to the **key** path only. The stored fact text, quotes and citations must
not change — citation integrity is non-negotiable.

## D2 — counts get an attribute slot, not a residual key

Add a categorical slot for counts: `cat:count:<subject-prefix>:<verb-stem>:<head-noun>` with the
number as the value.

- **Subject prefix**: reuse `_subject_prefix` on the text before the verb, so "user" and "the user"
  resolve alike.
- **Verb-stem**: the counting verb, from a small closed set: own, have, read, watch, run, buy, try,
  visit, attend, complete, spend, save, earn, score, collect, lead, take, eat, drink, play, write,
  paint. Only these fire the slot; anything else keeps its residual key.
- **Head noun**: the first content noun after the number, skipping prepositions ("of", "from", "in",
  "on", "at", "for", "with", "about") and possessives, singularised with the existing singulariser.
  "tried 2 of Emma's recipes" -> `emma`; "bought three tops from H&M" -> `top`.
- **Value**: the number only.

Documented limitation, to be written into `docs/compile-policies.md`: two counts of different things
under the same verb and head noun merge (e.g. "bought 3 tops" and "bought 5 tops from Zara" both key
on `bought:top`). That is intended — the attribute is "tops bought" — but it must be stated.

## D3 — compare within an entity, not a page

Replace page scope in `_supersede_contradictions` with **entity scope**: two facts may supersede or
flag each other only when their pages resolve to the same entity.

- Entity key = the last path segment of the page, lowercased, with `the-` stripped and separators
  normalised, so `misc/the-user`, `misc/user`, `people/user` and `decisions/user` all resolve to
  `user`, and `people/emma` resolves to `emma`.
- `projects/alpha` resolves to `alpha` and `projects/beta` to `beta`, so the false pairs that F1
  removed stay removed.
- The slot key must still match, and the categorical keys already carry the subject prefix, so a fact
  about a different person on the same page cannot collide.

This deliberately reverses part of F1. Record in `docs/compile-policies.md` P6: entity scope replaces
page scope because a page is a routing artefact, not an identity; the alpha/beta false pairs are
prevented by the entity key rather than by page boundaries.

## Tests (fail before, pass after; every one must fail under a mutant)

1. D1: `45dc21b6`'s pair — "tried two of Emma's recipes" (earlier) then "tried 3 of Emma's recipes"
   (later), same page: the first must be `superseded` by the second. Mutant: remove the number-word
   map, the test must fail.
2. D2: "The user bought three tops from H&M" then "The user bought five tops from H&M": the first is
   superseded. Mutant: disable the count slot, test must fail.
3. D2 negative: "The user bought three tops from H&M" then "The user bought 5 books": both stay
   active (different head nouns). Mutant: drop the head noun from the key, test must fail.
4. D3: the Fitbit pair from `eval/results/lme-db/08e075c7.db` shape — `misc/user` "6 months as of
   2023-06-18" and `people/user` "9 months as of 2023-09-02": the first must be superseded. Mutant:
   restore page scope, test must fail.
5. D3 negative: `projects/alpha` "first CI run failed" and `projects/beta` "first CI run failed" stay
   active together. Mutant: compare across entities, test must fail.
6. Regression: every test that passes at `0e8e7eb` still passes.

## Evidence to return

- The commit sha, the suite count, and each mutant's failure output.
- `eval/probe_phase17.py` on the 27 databases: superseded / flagged / duplicates_linked, against
  `0e8e7eb` = 0/13/39. Expect supersessions to return; report which, not just how many.
- `reports/phase18-report.md`: what changed, what it does not fix, and what was NOT verified.

## Constraints

- Do not edit `reports/ku-paired-result.md`, `reports/tes-review-5.md`, `docs/phase17-brief.md`.
- Do not edit `eval/longmemeval/ku_paired.py` or `eval/longmemeval/lme_eval.py` — the harness is
  accepted and frozen; Phase 18 changes the compiler only.
- Use the repo's `.venv/bin/python` for pytest (bare `python3` is Xcode 3.9 and fails
  collection).
- Commit on `main` with `-c user.name=Polly -c user.email=polly@local`. If publish-guard blocks the
  push, report the hits and add no allow entries.
