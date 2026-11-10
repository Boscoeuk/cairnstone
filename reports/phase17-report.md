# Phase 17 Part A — F1–F4 implemented

Status: **implementation complete, not accepted.** Part B (the knowledge-update experiment) has not
started. Tes reviews this before any run. HEAD before this work: `49aab62` (phase-17 brief rev 4).

## What changed

**F1 — contradiction scope restored to the page.** `_supersede_contradictions` now resets its
`seen`/`claims` state per page, as policy P6 and the phase-16 brief specify. A fact on page A can no
longer supersede or flag a fact on page B. Tests: `test_f1_fact_on_page_a_cannot_supersede_or_flag_a_fact_on_page_b`
and the counter-case `test_f1_same_page_genuine_contradiction_still_supersedes`.

**F2 — the N6 guard now protects the fix.** `test_n6_phrasing_variant_relationship_contradicts` asserts
the slot explicitly (`("cat:relationship_status:caroline", "married") in
_fact_slots("Caroline got married in May 2023")`), and a new
`test_n6_stale_single_is_superseded_by_the_married_fact` asserts the stale "single" fact is
`superseded` with `superseded_by` naming the married fact — not merely inactive.

**Mutant proof** (run for real, not asserted): with `_fact_slots` mutated to return `[]` for any text
containing "got married", both tests fail:

```
FAILED tests/test_phase15.py::test_n6_phrasing_variant_relationship_contradicts
FAILED tests/test_phase15.py::test_n6_stale_single_is_superseded_by_the_married_fact
2 failed in 0.08s
```

and pass unmutated.

**F3 — identifiers are part of the key; "as of" suffixes are not a value.** Digits that are part of a
name (`phase N`, `conv-NN`, `bNNN`) stay in the slot key instead of becoming the compared value, and a
bare trailing "as of <date>" clause is ignored when comparing values. Tests:
`test_f3_phase_identifiers_stay_active`, `test_f3_budget_identifiers_stay_active`,
`test_f3_bare_as_of_suffix_is_not_a_value`, `test_f3_genuine_value_change_still_supersedes`.

**F4 — state-verb immunity.** `married`, `wed`, `eloped`, `separated`, `engaged` and `relocated` are
recognised as state phrasings; "X married <Name>" is anchored as an event by `_MARRIED_VERB_RE`
(`\bmarried\s+[A-Z]`) so a bare "is married" is not misclassified as an event; `met`/`left`/`joined`
are dropped from the immunity rule rather than anchored, because the anchor could not separate "met her
husband and is married" from a genuine event. Tests: `test_f4_married_named_object_is_an_event`,
`test_f4_false_event_hits_do_not_make_states_permanent`, `test_f4_event_marker_classification`.

**A defect the F4 test exposed, fixed at the root.** `_subject_prefix` stripped only *trailing*
copulas, so "Caroline met her husband through work and is married" keyed as
`caroline met her husband through work and` and never compared against `caroline`; the later
"Caroline is single" could not retire it. The subject now ends at the first action verb. Planning
verbs (`plans`, `wants`, `hopes`) are deliberately excluded so a plan keeps its own slot
(`test_plan_fact_does_not_contradict_status_fact` still passes).

## Test counts

| | before (`49aab62`) | after |
|---|---|---|
| suite | 133 passed | **143 passed** |

Ten new tests in `tests/test_phase17.py`, one new and one strengthened in `tests/test_phase15.py`. No
existing assertion was weakened.

## Collateral probe — measured, on backup copies, two passes

Same corpus and method as Tes's probe (27 databases: `eval/dogfood/session.db`, the conv-26/conv-30
DBs, and the 22 LongMemEval DBs), run through `eval/probe_phase17.py` on SQLite **backup copies**:

```
TOTAL superseded=0 flagged=14 duplicates_linked=39
databases: 27
```

The second pass is a no-op on every database (idempotent), and P11 still halts a runaway pass.

Baseline reproduced at `fe71ff1` with the same script in a worktree:

```
TOTAL superseded=3 flagged=40 duplicates_linked=35
```

against the brief's recorded `fe71ff1` = 3 / 40 / 57 and `d73b6ae` = 0 / 9 / 33. My duplicate count is
**35, not 57** — the discrepancy is in what is counted (I count new `duplicate_of` links created by
the two passes; Tes's figure appears to count all linked rows in the corpus). Flagged and superseded
match exactly, so the comparison that matters here is sound, but the duplicate column should not be
quoted without saying which count it is.

**The three correct supersessions are lost, as the F1 decision anticipated.** They were cross-page
pairs. Verified example: in `eval/results/lme-db/08e075c7.db` the Fitbit tenure facts sit on
`misc/user` ("6 months as of 2023-06-18") and `people/user` ("9 months as of 2023-09-02"), so page
scope cannot compare them. This is recorded as a known limitation in `docs/compile-policies.md` P6,
with the entity-keyed fix named as out of scope for this phase.

**Residual false positive, documented not fixed:** the F4 change adds one flag on the corpus,
`cat:relationship_status:caroline` "Caroline is married" against "Caroline is becoming a single
parent" — a transition flagged against a state. Treating "becoming" as a plan rather than a value is
the likely fix; it is not in F1–F4's scope.

**Documentation drift corrected:** `docs/compile-policies.md` P7 still said dedupe keeps the *earliest*
capture as canonical. Phase 15 (N1) changed that to the latest, so P7 was wrong; it now matches the
code.

## What I did NOT verify

- **No question-level measurement.** Part B has not run. The only execution of the harness is a
  1-question smoke (`71315a70`, 29 min, before/after both correct, no consolidation mutations) — it is
  a plumbing check, not a result, and it was run on pre-freeze code.
- **No judge change.** The judge recipe, prompt and model are untouched, so results stay comparable
  with earlier phases.
- **No embeddings change.** The embedding endpoint and cache are untouched.
- **Cross-page contradictions remain unresolved** (measured above, not fixed).
- **The 14 remaining flags were not individually adjudicated.** I read the relationship-status ones;
  the occupation/location ones are the pre-existing residue Tes already audited at 17→3, and I have
  not re-audited each of them here.
