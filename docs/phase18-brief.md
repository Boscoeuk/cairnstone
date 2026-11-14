# Phase 18 brief (rev 2) — make the consolidation thesis testable, and make update detection work

**Owner:** Polly. **Implementer:** local OMP worker. **Reviewer:** Tes.
**Sources:** `reports/ku-paired-result.md` (n=20: arms a 0.75 / b 0.75, 0 mutations) and Tes's review
`tes-review-ku-paired.md` on card `t_d67491f3`, which ACCEPTED the measurement and corrected the
diagnosis.

## What Tes established, and what follows

1. **(b) = (a) was guaranteed by construction.** `compile_all` already runs `dedupe()` and
   `supersede_contradictions()`; `consolidate()` re-runs the same deterministic functions and is
   idempotent on an unchanged brain. The paired comparison therefore cannot see the pass, even with
   perfect detection. **The experiment design must change: arm (a) has to be a brain compiled WITHOUT
   the dedupe/supersede pass, and arm (b) that same brain after the pass.**
2. The evidence that detection fails is **0 supersessions at compile time across 20 brains**.
3. Causes 1-3 are confirmed but incomplete. The Emma pair needs number normalisation *and* an
   attribute slot that cuts modifier tails. Entity scope alone will not catch the H&M and yoga pairs
   because their key wording differs. The Luna pair (6 -> 9 months) is caught by none of the three
   fixes: the subject and verb differ.
4. Extraction defects exist and entity scope will inherit them: Luna is labelled a dog; two different
   Alexes are merged on `people/alex`.
5. The (c) 0.85 vs (a) 0.75 result is 2 discordant pairs, exact p=0.5 — a footnote, not a claim.

## Scope

Two workstreams, both required. **A** fixes the detector. **B** fixes the experiment so it can measure
the detector. Do not touch retrieval scoring, the brief format, the answer prompt or the judge.

### A. Detector (compiler)

**A1. Quantity slots, not just counts.** Extend the attribute-slot idea to any quantity carrying a
unit: counts, durations ("6 months", "9 months"), and frequencies ("twice a week", "three times a
week", "every two weeks"). Normalise frequencies to a per-week rate (once = 1, twice = 2, "N times" =
N, "every two weeks" = 0.5) and durations to a canonical unit (days). Key shape:
`cat:qty:<subject-prefix>:<attribute>:<unit>` with the normalised value. The attribute is the object
head noun (counts) or the measured noun (durations/frequencies), taken as the first content noun after
the quantity, skipping prepositions and possessives.

**A2. Number-word and frequency-word normalisation** before keying: zero..twenty, tens, hundred,
thousand, compounds; `a couple` -> 2, `a dozen` -> 12, `once` -> 1, `twice` -> 2. Key path only; the
stored fact text, quotes and citations must not change.

**A3. Verb-equivalence groups** so a paraphrase does not split the key: {own, have, bought, purchased,
got} for possession; {see, attend, visit, had a session with} for meetings; {tried, tasted, made} for
recipes. Keep the list small and documented.

**A4. Entity scope replaces page scope** in `_supersede_contradictions`: two facts may supersede or
flag each other only when their pages resolve to the same entity (last path segment, lowercased,
`the-` stripped, separators normalised, so `misc/user`, `misc/the-user`, `people/user` and
`decisions/user` all resolve to `user`; `projects/alpha` stays distinct from `projects/beta`). Record
in `docs/compile-policies.md` P6 that entity scope replaces page scope because a page is a routing
artefact, not an identity, and that alpha/beta separation is now enforced by the entity key.

**A5. Do NOT try to fix extraction in this phase.** Note the Luna dog/cat label and the merged Alexes
as known limitations in the report; entity scope inheriting them is accepted for now.

### B. Experiment design

**B1. Arm (a) must be unconsolidated.** Add an option to the compile path (`compile_all` /
`lme_eval.compile_question`) to skip the dedupe/supersede pass. `ku_paired.py` compiles arm (a)'s
pristine brain with that pass disabled, then runs `consolidate()` on the copy for arm (b). Record in
the row which mode each brain was compiled in. The sidecar must record it too, so a brain compiled in
the wrong mode is refused rather than reused.

**B2. Mechanism metric per question.** For each question report: facts active before the pass, facts
superseded by the pass, and whether the stale value of the superseded pair still appears in arm (a)'s
brief and in arm (b)'s brief. Accuracy at n=20 cannot see a mechanism this small; this metric can.

**B3. Regression table as unit tests, before any re-run.** Encode these pairs as tests, each failing
before the fix and passing after, each with a mutant proof:
- Emma (`45dc21b6`): "tried two of Emma's recipes from Emma's channel" -> "tried 3 of Emma's recipes".
- H&M (`4b24c848`): "bought three tops from H&M" (`people/user`) -> "already owns five tops from H&M"
  (`misc/user`) — requires A3 and A4 together.
- Yoga (`945e3d21`): "does yoga twice a week" (`misc/user`) -> "attends yoga classes three times a
  week" (`people/user`) — requires A1 and A4.
- Luna (`e61a7584`): "Luna has been with her owner for about 6 months" -> "The user has had Luna for
  about 9 months" — requires A1 and A3.
- Dr Smith (`2698e78f_abs`): "therapy session with Dr. Smith every two weeks" -> "sees Dr. Smith every
  week" — requires A1.
- Negatives that must stay active: alpha/beta CI facts; "bought 3 tops from H&M" vs "bought 5 books".

### C. Then re-run

Re-run `ku_paired.py` with arm (a) genuinely unconsolidated, the same budget and rate, on the
**74 eligible knowledge-update questions** (`p17-ids-config.json` currently lists 20; extend it and
record the new config sha256). Report: accuracy per arm, McNemar for (b) vs (a), the mechanism metric
distribution, and the number of questions where the stale fact stayed active.

## Constraints

- Do not edit `reports/tes-review-5.md`, `reports/tes-review-ku-paired.md` or `docs/phase17-brief.md`.
- `eval/longmemeval/ku_paired.py` and `lme_eval.py` MAY be edited now (Tes requires B1/B2).
- Use the repo's `.venv/bin/python` for pytest.
- Commit on `main` with `-c user.name=Polly -c user.email=polly@local`; if publish-guard blocks the
  push, report the hits and add no allow entries.
- Return `reports/phase18-report.md` with real pasted output and an explicit "what I did NOT verify".
