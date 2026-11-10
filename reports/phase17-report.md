# Phase 17 Part A — F1–F4 implemented

Status: **implementation revised after Tes review 5, not accepted.** Part B (the knowledge-update
experiment) has not started. Tes reviews this commit before any run. HEAD before this work:
`49aab62` (phase-17 brief rev 4); the reviewed head of the first cut was `d9a4da7`.

## Round 2 — tes-review-5 defects D1–D4

Tes rejected the first cut at `d9a4da7` (`reports/tes-review-5.md`). F1 (page scope) and F2 (the n6
guard) are accepted as they stand and are unchanged. D1, D2/D3 and D4 are fixed here.

**D1 — identifier rule inverted.** `_is_identifier_digit` treated every non-boilerplate word before a
number as an identifier label, so "owns 15" and "owns 17" keyed apart and a genuine count update never
superseded (8 of 12 probes). The rule now inverts: a digit is part of a name only when it is attached
to a word (`b600`, `v2`), hyphen-joined to a label (`conv-26`, `phase-1`) or preceded by a short
identifier-label list (`phase`, `conv`, `sample`, `budget`, `n`, `v`, `version`, `tier`, `step`,
`port`, `pid`, `issue`, `id`, `pr`, …). Every other preceding word — a verb, a quantifier, an
adjective — leaves the number a value. Tests: `test_d1_count_update_after_a_verb_still_supersedes`
(12 parametrised pairs, including "owns 15 -> 17" and "has read 12 -> 15") and
`test_d1_verb_and_quantifier_labels_do_not_enter_the_key`. Mutant proof: restoring F3b's rule
(`9 failed, 4 passed`) fails all 8 count-update tests that were broken plus the unit test; unmutated
all pass. Measured on the same-page pairs with Tes's `ku_pairs.py` script: **12 of 12 now supersede**
(at `d9a4da7` it was 4 of 12).

**D2/D3 — relationship slot requires a main-clause predicate.** `_fact_slots` matched
single/dating/engaged/married anywhere in the sentence, and after F4's subject cut an incidental word
landed on the subject's bare live key. The slot is now formed by `_relationship_status_slot` only
when the category word is the predicate of the main clause: subject + copula/state verb + optional
short adverb, either as the clause's first predicate or conjoined with "and" ("Caroline is married",
"Caroline is now dating someone", "Caroline got married", "Caroline met her husband through work and
is married", "Pocahontas married John Rolfe"). Rejected: relative clauses ("who is …"), matches after
a preposition or any non-copula word ("about online dating", "is working on …"), noun modifiers
("single parent", "single-action", "engaged guests", "single-hop") and plans ("is getting married",
"plans to become a single parent"). Tests: `test_d2_incidental_category_word_does_not_supersede_status`
(10 parametrised pairs), `test_d2_relationship_slot_requires_a_main_clause_predicate`, and
`test_d3_caroline_residual_is_not_a_supersession_with_later_stamps` (the documented Caroline pair with
a later timestamp). Mutant proof: restoring the anywhere-in-the-sentence match gives `8 failed, 4
passed`, including all three D2 rows that were supersessions at `d9a4da7` and the D3 pair; unmutated
all pass. Measured with Tes's `f4_merge.py` script: only the real "Caroline is single <- Caroline is
married" pair supersedes; the other 10 stay active.

**D4 — documentation corrected.** `docs/compile-policies.md` P6 no longer cites the review-4
`projects/alpha`/`projects/beta` example as a corpus fact. It now records what the 27-database probe
actually measured: 3 genuine supersessions lost, **2 cross-page** (Fitbit `08e075c7`, Dear Evan Hansen
`gpt4_76048e76`) and **1 same-page** that F3a removed correctly (the dogfood "first CI run failed"
restamped "as of 2026-11-06"). P7 now names the two duplicate measurements distinctly:
`duplicates_linked` (the counter `consolidate()` returns: 35 at `fe71ff1`, 39 at `d9a4da7`) versus
"rows whose `duplicate_of` changed" (57 at `fe71ff1`, 61 at `d9a4da7`). The brief's P1 example is
annotated the same way.

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
verbs (`plans`, `wants`, `hopes`) are deliberately excluded, and since round 2 a plan forms no
relationship slot at all (`test_plan_fact_does_not_contradict_status_fact` still passes).

## Test counts

| | before (`49aab62`) | after round 1 (`d9a4da7`) | after round 2 |
|---|---|---|---|
| suite | 133 passed | 143 passed | **167 passed, 1 skipped** |

Round 1 added ten tests in `tests/test_phase17.py`, one new and one strengthened in
`tests/test_phase15.py`. Round 2 adds 24 more in `tests/test_phase17.py` (12 D1 count-update pairs,
1 D1 key unit test, 10 D2 incidental pairs, 1 D2 predicate unit test, 1 D3 pair). No existing
assertion was weakened. The one skip is the gitignored local redaction-rules test; it passes in the
main checkout.

## Collateral probe — measured, on backup copies, two passes

Same corpus and method as Tes's probe (27 databases: `eval/dogfood/session.db`, the conv-26/conv-30
DBs, and the 22 LongMemEval DBs), run through `eval/probe_phase17.py` on SQLite **backup copies**:

```
TOTAL superseded=0 flagged=13 duplicates_linked=39
databases: 27
```

Per-database delta from the reviewed head `d9a4da7` (0 / 14 / 39): **one flag removed, nothing else
changed.**

| DB | `d9a4da7` superseded/flagged/duplicates_linked | round 2 | delta |
|---|---|---|---|
| `session.db` | 0 / 2 / 9 | 0 / **1** / 9 | flagged -1 (the Caroline residual) |
| `conv-26.db` (×2 result dirs) | 0 / 1 / 1 | 0 / 1 / 1 | none |
| `conv-30.db` (×2 result dirs) | 0 / 1 / 1 | 0 / 1 / 1 | none |
| `0e5e2d1a.db` | 0 / 2 / 2 | 0 / 2 / 2 | none |
| `7527f7e2.db` | 0 / 3 / 0 | 0 / 3 / 0 | none |
| `85fa3a3f.db` | 0 / 1 / 2 | 0 / 1 / 2 | none |
| `c8090214.db` | 0 / 1 / 4 | 0 / 1 / 4 | none |
| `gpt4_76048e76.db` | 0 / 1 / 2 | 0 / 1 / 2 | none |
| other 17 DBs | 0 / 0 / * | 0 / 0 / * | none |

The removed flag is exactly `cat:relationship_status:caroline` — "Caroline is married" against
"Caroline is becoming a single parent". No new flag appeared and no supersession changed.

**No supersessions came back from D1 on this corpus.** The D1 fix restores the mechanism (12 of 12
same-page count pairs now supersede), but these 27 databases hold no same-page count-update pair of
that shape, so the total stays 0. Measured key impact: the numeric key differs from `d9a4da7` on
1,079 of the 10,300 unique active fact texts; 469 distinct preceding words that F3b treated as
identifier labels are now value contexts, across 2,803 digit matches.

The second pass is a no-op on every database (idempotent), and P11 still halts a runaway pass.

Baseline reproduced at `fe71ff1` with the same script in a worktree:

```
TOTAL superseded=3 flagged=40 duplicates_linked=35
```

`duplicates_linked` is the counter `consolidate()` returns. The brief's recorded `fe71ff1` figure of
57 is a **different measurement** — rows whose `duplicate_of` value changed (57 at `fe71ff1`, 61 at
`d9a4da7`). Both numbers are right; they count different things, and P7 now names them separately.

**The three correct supersessions are lost, as the F1 decision anticipated.** Two are cross-page
pairs: in `eval/results/lme-db/08e075c7.db` the Fitbit tenure facts sit on `misc/user` ("6 months as
of 2023-06-18") and `people/user` ("9 months as of 2023-09-02"), and in `gpt4_76048e76.db` the Dear
Evan Hansen "since December 2022 -> since 2022-12-01" pair is also `misc/user` vs `people/user`. Page
scope cannot compare either. The third is **same-page** and is not a page-scope loss: it is the
dogfood `projects/cairnstone` "first CI run failed" fact against the same sentence restamped "as of
2026-11-06", which F3a correctly treats as one claim. This is recorded as a known limitation in
`docs/compile-policies.md` P6, with the entity-keyed fix named as out of scope for this phase.

**Residual false positive — fixed in round 2.** Round 1 added one flag on the corpus,
`cat:relationship_status:caroline` "Caroline is married" against "Caroline is becoming a single
parent" — a transition flagged against a state. The D2 main-clause predicate rule removes it: the
transition forms no relationship slot at all, and the same pair with later timestamps no longer
supersedes (D3, `test_d3_caroline_residual_is_not_a_supersession_with_later_stamps`).

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
- **The 13 remaining flags were not individually adjudicated.** I read the relationship-status ones
  (one, the Caroline ambiguity flag at equal timestamps); the occupation/location ones are the
  pre-existing residue Tes already audited at 17→3, and I have not re-audited each of them here.
