# Phase 18 report — detector fixes (Part A) and B3 regression tests

**Date:** 2026-11-15. **Implementer:** local OMP worker. **Scope:** Part A (A1–A5) of
`docs/phase18-brief.md` rev 2 plus the B3 regression table. Part B (the experiment redesign,
B1/B2) is NOT touched: `eval/longmemeval/ku_paired.py`, `lme_eval.py` and the eval harness are
unchanged, per instruction.

## What was implemented

- **A1 — quantity slots** (`src/cairnstone/compile.py`, `_quantity_slots`): counts, durations and
  frequencies become slots with key shape `cat:qty:<subject>:<attribute>:<unit>`. Durations
  normalise to days (month = 30, year = 365); frequencies normalise to a per-week rate
  ("twice a week" = 2, "every two weeks" = 0.5). The attribute is the first content noun after the
  quantity — the object noun for a count, the unit word ("month", "week") for a duration or
  frequency. The subject is the nearest content noun before the quantity, found by a backward scan
  that skips verbs, prepositions, articles, conjunctions, determiners, titles and adverbs, skips
  possessive phrases whole ("her owner") and folds compound heads to their modifier ("yoga
  classes" → "yoga").
- **A2 — number/frequency-word normalisation** on the key path only: zero–twenty, tens, hundred,
  thousand, "a couple" → 2, "a dozen" → 12, once → 1, twice → 2. Stored fact text, quotes and
  citations are never rewritten (the slot value is normalised; the fact row is untouched).
- **A3 — verb-equivalence lexicon** (`_VERB_GROUPS`): possession {own, have, bought, purchased,
  got}, meetings {see, attend, visit, had a session with}, recipes {tried, tasted, made}. They let
  the backward scan recognise irregular past verbs ("bought", "has", "had") as verbs; pure copulas
  and do/does/did are recognised without the groups.
- **A4 — entity scope** (`_page_entity`, `_supersede_contradictions`): the comparison state resets
  per resolved entity (last path segment, lowercased, `the-` stripped, separators normalised), so
  `misc/user`, `misc/the-user`, `people/user` and `decisions/user` compare, while
  `projects/alpha` and `projects/beta` never do. Documented in `docs/compile-policies.md` P6.
- **A5 — no extraction fixes.** Known limitations recorded below.
- Two guards found necessary while measuring (both documented in code):
  - a fact carrying identifier digits (phase 17 D1 — "phase 1", "budget 600") forms no quantity
    slots, so contextualised numbers ("931 tokens" at "budget 600") cannot collide across
    configurations (keeps the F3 tests green);
  - a fact that states two different values for one attribute ("weights including 140 lb, 200 lb")
    is enumerating, not updating — the key forms no slot, so a fact can never contradict itself.
  - the N11 event/state exemption does not apply to `cat:qty:` slots: a quantity is a measurement,
    and "bought three tops" / "owns five tops" are two readings of one possession measurement.

## Tests

`tests/test_phase18.py` — 10 tests: the five B3 pairs (Emma, H&M, Yoga, Luna, Dr Smith) plus the
alpha/beta and tops-vs-books negatives and three unit views of A1–A4.

Failing before the fix (compile.py reverted to HEAD 2cf8516, new tests run against it):

```
  - superseded
  + active
5 failed, 5 deselected in 0.13s
```

Passing after the fix, full suite:

```
$ .venv/bin/python -m pytest -q
.........  [100%]
225 passed in 7.91s
```

(215 at HEAD + 10 new.)

## Mutant proofs (each mutation applied to src/cairnstone/compile.py, tests run, reverted)

1. **Disable the qty slot** (`return []` at the top of `_quantity_slots`):

```
5 failed, 5 deselected in 0.12s   <- Emma, H&M, Yoga, Luna AND Dr Smith all fail
```

2. **Restore page scope** (group by `page_id` instead of `_page_entity(path)`):

```
FAILED tests/test_phase18.py::test_b3_hm_possession_paraphrase_across_pages_supersedes
FAILED tests/test_phase18.py::test_b3_yoga_frequency_across_pages_supersedes
2 failed, 3 passed, 5 deselected in 0.07s   <- exactly the two cross-page pairs
```

3. **Drop the verb groups** (`_GROUP_VERB_STEMS = frozenset()`):

```
FAILED tests/test_phase18.py::test_b3_hm_possession_paraphrase_across_pages_supersedes
FAILED tests/test_phase18.py::test_b3_yoga_frequency_across_pages_supersedes
FAILED tests/test_phase18.py::test_b3_luna_duration_supersedes
3 failed, 2 passed, 5 deselected in 0.08s
```

Luna fails as specified. H&M also fails (expected — the brief says H&M requires A3 and A4
together). Yoga also fails under this mutant: with the groups gone the compound-head fold in the
subject scan can no longer tell "attends" from a noun and over-folds; the yoga pair itself needs
only A1 and A4 to pass (it passes with all mechanisms active), but its key derivation does lean on
the group check. Emma and Dr Smith stay green under the mutant.

## 27-database probe (eval/probe_phase17.py, two passes per DB, temp backup copies)

```
TOTAL superseded=5 flagged=86 duplicates_linked=39
databases: 27
```

Against the baseline at HEAD (**0 / 13 / 39**): superseded 0 → **5**, flagged 13 → **86**,
duplicates_linked **39** (unchanged — dedupe is untouched). Pass 2 of `consolidate()` found zero
new mutations on every database (the pass stays idempotent).

The five supersessions the passes made, named:

- `eval/dogfood/../cairn-db/conv-26.db` and `cairnstone-db/conv-26.db` (both variants):
  "Caroline has known her friends for 4 years, since she moved from her home country." superseded
  by "Caroline turned 18 in 2013 (her 18th birthday was ten years before 2023-06-27)." — both key
  `cat:qty:caroline:year:day` (1460 vs 3650 days). **This one is a false positive** (friendship
  duration vs age): the unit-noun attribute "year" is generic. Recorded as a known limitation.
- `eval/results/lme-db/08e075c7.db`: "The user has been using a Fitbit Charge 3 for 6 months as of
  2023-06-18" superseded by "... for 9 months as of 2023-09-02" — the cross-page tenure pair P6
  documented as lost (facts on `misc/user` and `people/user`); recovered by entity scope + the
  duration slot.
- `eval/results/lme-db/0f05491a.db`: "Reaching the Gold level on the Starbucks Rewards app
  requires 125 stars within a 12-month period" superseded by "Reaching Gold level on Starbucks
  Rewards requires 120 stars".
- `eval/results/lme-db/gpt4_76048e76.db`: "User has been listening to the original cast recording
  of Dear Evan Hansen nonstop since December 2022" superseded by "... since 2022-12-01" — the
  other cross-page pair P6 documented as lost; recovered by entity scope.

Flag composition (86 new flags, classified by instrumenting the probe): 67 `cat:qty:*`
equal-instant ambiguities (P6: same capture stamp → flag, never supersede), 6 occupation,
8 location, 1 relationship_status (advisory D5b slots now comparing across pages of one entity —
the designed consequence of A4), 4 residual. 98 further flags that the first measurement showed
were facts contradicting **themselves** (enumerations like "140 lb, 200 lb") were eliminated by the
enumeration guard above; after the guard no self-flags and no identical-text cross-fact flags
remain.

## Known limitations (A5 — not fixed here)

- Extraction defects are inherited, not fixed: Luna is labelled a dog in `e61a7584`
  ("Luna is the user's dog" vs "Luna is the user's cat" on the same page) and two different Alexes
  are merged on `people/alex`. Entity scope inherits both.
- The unit-noun attribute makes duration/frequency keys coarse: two different "year" claims about
  one entity collide (the Caroline false positive above).
- The subject scan is a heuristic backward walk with a small closed-class verb list; unrecognised
  verb forms ("took", "lasts") can land the subject on the wrong noun, which costs recall (missed
  detections), not correctness (a wrong supersession needs equal subject, attribute and unit).
- "a couple of weeks" reads as a count of the noun "week", not a 14-day duration.

## What I did NOT verify

- Part B (B1/B2): the experiment redesign, the mechanism metric and the 74-question re-run are not
  started — the eval harness is untouched, per instruction.
- The probe runs consolidation over **backup copies**; the 27 real database files were opened
  read-only by the backup API and never written.
- Retrieval scoring, brief format, answer prompt and judge are untested against the new slots —
  out of scope per the brief.
- The 86 new flags were classified by my instrumentation script, not by hand-reading all 86.
- The eval harness was not re-run end to end (no model calls were made at all in this phase; the
  B3 tests and the probe are deterministic and model-free).
