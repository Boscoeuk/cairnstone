# Phase 15 report — closing N1–N5, the migration backfill and P11

Date: 2026-11-07. Specification: `reports/tes-review-2.md`. Executed by Polly after the phase-15
worker was SIGTERM'd mid-task with four tests failing and no report; the work below was completed
and verified by hand.

Boundaries honoured: extraction prompts, retrieval ranking, the citation invariant, `eval/harness.py`,
`eval/dogfood/`, `eval/longmemeval/` and every measured number untouched.

## What changed

`src/cairnstone/store.py`
- `normalise_timestamp()` + `parse_timestamp()`: ISO-8601, `2023/04/10 (Mon) 17:50` and
  `1:56 pm on 8 May, 2023` all parse. `add_capture` stores the instant in `captured_at` and the
  original text in the new `captured_at_text` column (provenance).
- Migration: normalises existing rows where parseable, reports unparseable ones on stderr rather
  than guessing, and backfills `compiled_at` for captures that already have facts (Tes review 2
  item 5).

`src/cairnstone/compile.py`
- **N1**: `dedupe` makes the LATEST capture canonical (tie-break capture id, then fact id) instead
  of the lowest fact id, and repoints existing duplicates so `duplicate_of` always names a live
  canonical row rather than forming a chain. `_supersede_contradictions` compares each fact against
  its duplicate cluster's latest timestamp.
- **N2**: recency is compared on normalised instants, not strings.
- **N5**: equal instants are flagged and neither fact is superseded (policy P6). The equality test
  compares the instant only — an earlier version compared `(stamp, capture_id)`, which made the
  branch unreachable for two different captures.
- **P11**: `consolidate(..., max_mutation_rate=...)` halts and reports when a pass would mutate more
  than the allowed fraction of active facts; `cli._health_backoff` yields to interactive traffic
  before model calls.
- **New defect found live (call it N6)**: `_fact_slots` keyed categorical slots on the text before
  the matched value, so "Caroline is single" (`caroline is`) and "Caroline got married in May 2023"
  (`caroline got`) never compared and both stayed active. The key now identifies the subject, with
  trailing copulas/auxiliaries/time adverbs stripped (`_subject_prefix`).

`src/cairnstone/retrieve.py`
- **N3**: `build_brief` emits a contradiction note when selected records on the same page disagree,
  so a flagged fact is visible to a reader instead of being silently dropped.
- **N4**: occupation only forms a slot when the complement's first word is a role noun; location
  values stop before trailing modifier clauses.

`src/cairnstone/cli.py`
- `consolidate` command gains `--max-mutation-rate`; `ingest` gains `--captured-at` with an explicit
  warning that omitting it means "ingest time".

## Verification

`.venv/bin/python -m pytest -q` → **113 passed** (104 before; `tests/test_phase15.py` adds 9: N1 batch
re-assertion, duplicate chains, N2 LoCoMo stamp ordering, N2 slash-date normalisation, N4 identity
false-positive, N4 real occupation change, N5 equal timestamps, N6 phrasing variant, migration
backfill).

Two phase-14 tests encoded the old behaviour and were updated deliberately, with the reason in the
docstring: `test_d3_equal_timestamps_tie_break_on_capture_id` → `..._flag_under_policy_p6` (P6
supersedes the capture-id tie-break on an exact tie), and the D1/spelling tests now assert the
canonical row is the latest capture. No assertion was weakened.

`eval/consolidation_repro.py` extended with N1 and N2. Actual output:

```
=== Scenario N1 (phase 15: re-assertion inside one batch) ===
after pass 1: {'duplicates_linked': 1, 'superseded': 1, 'flagged': 0}
  1   Caroline is single    active      sup_by -   dup_of 3   cap 1
  2   Caroline is married   superseded  sup_by 3   dup_of -   cap 2
  3   Caroline is single    active      sup_by -   dup_of -   cap 3
after pass 2: {'duplicates_linked': 0, 'superseded': 0, 'flagged': 0}
second pass changed nothing: OK

=== Scenario N2 (phase 15: LoCoMo-style stamps) ===
after pass 1: {'duplicates_linked': 0, 'superseded': 1, 'flagged': 0}
  1   Caroline is single   superseded  sup_by 2  cap 1
  2   Caroline is married  active      sup_by -  cap 2
after pass 2: {'duplicates_linked': 0, 'superseded': 0, 'flagged': 0}
second change nothing: OK
```

All five scenarios converge in one pass and the second pass is a no-op.

### N2 measurement on the real LoCoMo databases

`eval/measure_timestamp_order.py` on copies (originals untouched):

```
conv-26: 419 captures, 87571 pairs | wrongly ordered before=43017 after=0 | unparseable=0
conv-30: 369 captures, 67896 pairs | wrongly ordered before=30760 after=0 | unparseable=0
```

Tes's 81/171 and 79/171 were over distinct session-stamp pairs; over every capture pair the raw
strings mis-order 49% and 45% of them. After normalisation: zero, on both.

## Live end-to-end runs — both endpoints

Same four captures (Berlin/single May, Lisbon/married June, single July, duplicate Berlin/single
August) ingested with explicit timestamps, compiled, then consolidated twice.

GLM (`http://127.0.0.1:8460/v1`, `glm-5.3-flash`):

```
ok: compiled captures=4 accepted=7 rejected=0 duplicates_linked=3 superseded=1 failed_captures=[]
ok: consolidated duplicates_linked=0 superseded=0 flagged=0
ok: consolidated duplicates_linked=0 superseded=0 flagged=0
  4   Caroline got married in May 2023   superseded  sup_by=7
  7   Caroline is single                 active
  FLAG fact=3 {"contradicts": 6, "slot": "cat:location:caroline", "values": [["lisbon"], ["berlin"]]}
```

Second local node (`http://<lan-node>:8889/v1`, `local-judge`):

```
ok: compiled captures=4 accepted=7 rejected=0 duplicates_linked=3 superseded=1 failed_captures=[]
ok: consolidated duplicates_linked=0 superseded=0 flagged=0
ok: consolidated duplicates_linked=0 superseded=0 flagged=0
  4   Caroline is married.   superseded  sup_by=7
  7   Caroline is single.    active
  FLAG fact=3 {"contradicts": 6, "slot": "cat:location:caroline", "values": [["lisbon"], ["berlin"]]}
```

The first GLM run (before the N6 fix) left both "Caroline got married in May 2023" and
"Caroline is single" active — that is how the phrasing defect was found. After the fix both
endpoints converge to the same correct state: the July/August single is active, the marriage is
superseded, and the unresolved Berlin/Lisbon move is flagged with both facts kept.

Brief for "Where does Caroline live?" after consolidation returns Lisbon and Berlin with citations
(`[capture live-glm-2 span 10:38]`, `[capture live-glm-4 span 10:26]`) — the older fact is no longer
hidden.

## Not verified

- The LoCoMo and LongMemEval numbers were **not** re-run against this compiler. Consolidation does
  not change extraction, but `_fact_slots`/`dedupe` changes could move duplicate counts on those
  brains. Treat the 78.0% figure as measured on the previous commit.
- `--max-mutation-rate` is exercised only by its unit test; no live brain has tripped it.
- The migration's unparseable-stamp path has no real data to test against (both LoCoMo DBs parse
  fully).
