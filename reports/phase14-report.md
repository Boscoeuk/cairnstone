# Phase 14 report — making the nightly consolidation pass real

Date: 2026-11-06. Specification: `reports/tes-consolidation-1.md` (§Defects D1–D6).
Boundaries honoured: `eval/harness.py`, `eval/dogfood/`, `eval/longmemeval/` untouched;
extraction behaviour, retrieval ranking and the citation invariant
(`quote == captures.content[span_start:span_end]`) unchanged.

## What changed

### D1 — stale canonical fact survives a pass
`src/cairnstone/compile.py` — `supersede_contradictions` now scans only canonical rows
(`AND f.duplicate_of IS NULL`), so a duplicate can no longer replace the canonical fact in
the comparison map and hide a contradiction. One pass converges; the public
`supersede_contradictions()` return type (int) is preserved, with the core logic in
`_supersede_contradictions()` returning `(superseded, flagged)`.

### D2 — `compile` re-extracted every capture every run
- `src/cairnstone/store.py`: `captures` gains a `compiled_at TEXT` column (schema +
  a migration in `init_db` for existing databases), plus `mark_capture_compiled()`.
- `src/cairnstone/compile.py`: `compile_capture` marks the capture compiled after a
  successful extraction.
- `src/cairnstone/cli.py`: `cmd_compile` selects only `WHERE compiled_at IS NULL`; with
  no new captures it skips the model entirely (no endpoint requirement) and still runs the
  model-free consolidation. New `cairnstone consolidate --db …` command runs
  `dedupe` + `supersede_contradictions` + contradiction flagging over the whole brain with
  **no model calls** — the nightly entry point. Exposed as `compile.consolidate(conn, brain_id)`
  returning `{"duplicates_linked", "superseded", "flagged"}`.

### D3 — "newer" was a higher capture id
`_supersede_contradictions` joins `captures` and orders recency by
`(captures.captured_at, capture_id)`. Documented tie-break: equal timestamps fall back to
capture id (insert order); a fact with an unknown timestamp cannot occur because
`captures.captured_at` is `NOT NULL`. Fact id is never the clock.

### D4 — swap path recorded the wrong value
When the comparison swaps rows so the older capture loses, the stored values swap with the
rows (`old_value, new_value = new_value, old_value`), so the comparison map always holds a
value that belongs to its row. A following same-capture fact is no longer judged a
contradiction of itself, and a fact is never superseded by a duplicate of its own claim.

### D5 — contradiction detection covered only numbers/dates + a six-word lexicon
- (a) `_CATEGORY_SLOTS` extended with **location** (`lives in|lived in|moved to|is moving to`)
  and **occupation** (`works as|work as|working as|is a|is an`) entries. The regex's first
  group is the slot value; `_slot_value()` folds the tail to content tokens with
  dates/numbers removed, so "moved to Lisbon on 2023-05-25" and "lives in Lisbon" carry the
  same value (`lisbon`) and "working as a nurse for 4 years" / "is a nurse" compare equal.
- (b) Location and occupation are **advisory** slots: when values differ, the pass writes a
  `fact.contradiction_flagged` change event (subject = older fact, payload records
  `contradicts`, `slot`, `values`) and retracts nothing. Flag writes are idempotent (an
  identical event is not duplicated), so repeated passes do not grow the event log.
  Relationship-status and numeric/date slots remain decisive (supersede) as before.

### D6 — retrieval's near-duplicate collapse kept the stale side
`src/cairnstone/retrieve.py` — `select_facts` now computes whether a Jaccard-cluster's
members share a slot key with different values (`_cluster_disagrees`, using the compile
slot machinery via a deferred import to avoid the existing `compile → retrieve` import
edge). On disagreement the cluster winner is the fact from the latest `captured_at`
(falling back to capture id, then fact id); otherwise the existing time-frame/score/id
ordering applies unchanged.

### Near-duplicate detection — spelling variants
`_claim_key` now folds the base to word tokens with a British/American spelling map
(`favourite→favorite`, `colour→color`, `organise→organize`, …), so case, punctuation and
spelling variants no longer split a duplicate pair.

## New command usage

```bash
cairnstone consolidate --db brain.db
# ok: consolidated duplicates_linked=N superseded=N flagged=N
```

No model, no endpoint requirement. `compile` remains the extraction entry point but now
processes only captures without `compiled_at`.

## Tests

`tests/test_phase14.py` — 11 deterministic tests (no model, no network), one or more per
defect: D1 two-pass convergence + idempotency, D3 out-of-order captures + equal-timestamp
tie-break, D4 swap/value agreement + never-superseded-by-own-duplicate, D5 location flag
(+ occupation rewording not flagged, occupation change flagged), D6 stale-side retrieval
("Where does Caroline live?" → Lisbon), spelling-variant duplicate linking, D2
`compiled_at` bookkeeping.

```
$ python3 -m pytest -q
........................................................................ [ 69%]
................................                                         [100%]
104 passed in 7.80s
```

(93 pre-existing + 11 new; all green, no existing test weakened.)

## Deterministic scenario script

`eval/consolidation_repro.py` (no model) rebuilds the report's B1 (D1), B3 (D3) and run_d
(D4) scenarios and prints the fact table after one and two passes:

```
$ python3 eval/consolidation_repro.py

=== Scenario B1 (D1: duplicate hides canonical fact) ===
after pass 1: {'duplicates_linked': 1, 'superseded': 1, 'flagged': 0}
  id  text                                          status       sup_by  dup_of  cap
  1   Caroline is single                            superseded 3       -       1
  2   Caroline is single                            active     -       1       2
  3   Caroline is married                           active     -       -       3
after pass 2: {'duplicates_linked': 0, 'superseded': 0, 'flagged': 0}
second pass changed nothing: OK

=== Scenario B3 (D3: out-of-order captures) ===
after pass 1: {'duplicates_linked': 0, 'superseded': 1, 'flagged': 0}
  id  text                                          status       sup_by  dup_of  cap
  1   Caroline has been a nurse for 5 years         active     -       -       1
  2   Caroline has been a nurse for 4 years         superseded 1       -       2
after pass 2: {'duplicates_linked': 0, 'superseded': 0, 'flagged': 0}
second pass changed nothing: OK

=== Scenario run_d (D4: swap records wrong value) ===
after pass 1: {'duplicates_linked': 0, 'superseded': 1, 'flagged': 0}
  id  text                                          status       sup_by  dup_of  cap
  1   Caroline is married                           active     -       -       2
  2   Caroline is single                            superseded 1       -       1
  3   Caroline is married and happy                 active     -       -       2
after pass 2: {'duplicates_linked': 0, 'superseded': 0, 'flagged': 0}
second pass changed nothing: OK

All scenarios: one pass converged, second pass was a no-op.
```

## Live smoke

Local endpoint `http://127.0.0.1:8460/v1` (`glm-5.3-flash`); embeddings `127.0.0.1:1234`
(nomic). Two captures ingested ("I live in Berlin and I am single" / "I moved to Lisbon
last month and I got married"), then:

```
$ cairnstone compile --db smoke.db
ok: compiled captures=2 accepted=4 rejected=0 duplicates_linked=0 superseded=0 failed_captures=[]

$ cairnstone consolidate --db smoke.db
ok: consolidated duplicates_linked=0 superseded=0 flagged=0
$ cairnstone consolidate --db smoke.db   # second run
ok: consolidated duplicates_linked=0 superseded=0 flagged=0

$ cairnstone compile --db smoke.db       # re-run: nothing left to extract
ok: compiled captures=0 accepted=0 rejected=0 duplicates_linked=0 superseded=0 failed_captures=[]
```

The second `consolidate` reported no changes (idempotent), and the re-run `compile`
processed 0 captures — no re-extraction, no model calls. The live run also wrote a real
`fact.contradiction_flagged` event for the Berlin/Lisbon location change
(`{"contradicts": 3, "slot": "cat:location:caroline", "values": [["berlin"], ["lisbon"]]}`),
and a live `brief` for "Where does Caroline live?" answered "Caroline lives in Lisbon."

## Not verified / known limits

- The live smoke's extracted wording ("moved to Lisbon", "got married") does not trigger a
  supersede for relationship status because the categorical slot key keeps the text before
  the matched word ("caroline got" vs "caroline is") — the same design limit the source
  report notes for plans vs statuses. The D5 flag path itself was exercised live (location)
  and deterministically (tests).
- D6's collapse only applies when clustered facts share a slot key; facts with different
  markers (e.g. "lives in" vs "moved to") are not clustered and both stay in the brief, by
  design (the flag is advisory).
- Model variance: the live smoke ran once; extraction wording may differ between runs.
- The P11 `max_mutation_rate` halt and `/health` back-off noted in the source report are
  still not implemented (out of scope for this phase).
