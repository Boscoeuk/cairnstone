# Phase 15 — close the consolidation defects Tes found, and make "nightly" real

Specification: `reports/tes-review-2.md` (defects N1–N5, item 5, and "README nightly evolution
verdict"). Do not change extraction prompts, retrieval ranking, the citation invariant
(`quote == captures.content[span_start:span_end]`), `eval/harness.py`, or any measured number.

## Fixes, in Tes's priority order

**N1 — a later re-assertion is hidden as a duplicate.** `dedupe` makes the lowest fact id canonical,
and the contradiction scan reads only that canonical row's timestamp. So single (May), married (Jun),
single (Jul) ends with "married" active and the July truth hidden as a duplicate. Canonical must be
chosen by latest `captured_at` (tie-break capture id), and the comparison must use the latest
timestamp among a claim's duplicates.

**N2 — timestamps compared as raw strings.** Normalise `captured_at` to ISO-8601 UTC at
`add_capture`. Must parse at least: ISO-8601, `2023/04/10 (Mon) 17:50`, and LoCoMo's
`1:56 pm on 8 May, 2023`. Store the original in a new `captured_at_text` column for provenance.
Migration: normalise existing rows where parseable; leave unparseable rows as-is and report them
rather than guessing. Tes measured 81/171 wrongly ordered pairs on conv-26 and 79/171 on conv-30 —
after this fix, re-run that measurement and report the new count.

**N3 — a flagged contradiction disappears from briefs.** A flagged (unresolved) fact must not be
hidden more thoroughly than a superseded one. Include the selected fact *and* a short
"Earlier: … (contradicts …)" line when the cluster disagrees, inside the existing budget. The flag
must be visible to a reader of the brief.

**N4 — occupation slot precision.** All 17 flags on real data are false positives (identity
sentences: "X is an independent reimplementation"). Tighten so that `is a|is an` only forms an
occupation slot when the subject is a person and the complement is a role noun; and make the
location value stop at a preposition or comma so "lives in Lisbon" and "lives in Lisbon with her
husband" compare equal. Re-run the flag count on dogfood and the two LoCoMo DBs: report how many
remain and hand-audit each remaining flag, stating for each whether it is true or false.

**N5 — equal timestamps.** Policy P6 says equal timestamps must be flagged with neither fact
superseded. The code supersedes by capture id. Implement P6 and align the docstring.

**Item 5 — migration backfill.** Opening a pre-phase-14 DB adds `compiled_at` but never marks the
306 captures that already produced facts, so the first `compile` re-extracts all 366. Backfill
`compiled_at` for captures that already have facts. State explicitly what you do about captures
that produced zero facts, and why.

**Item 2 — `ingest` cannot set a time.** Add `--captured-at` to `cairnstone ingest`; a missing value
must not silently mean "now" for a backfill (keep the current default but say so in help text).

**P11 — implement what the policy claims.** `docs/compile-policies.md` P11 promises a
`max_mutation_rate` halt and a `/health` back-off. Implement the mutation-rate halt in
`consolidate` (halt and report if superseded+flagged exceeds the rate against active facts) and the
`/health` check before model calls. If you judge the back-off too costly, say so and change the
policy text instead of leaving it claiming something untrue.

## Verification you must produce

1. `.venv/bin/python -m pytest -q` green (the repo venv is the only interpreter that has
   `cairnstone` and `pytest` installed; bare `python3` is Xcode 3.9 and fails collection), with new
   deterministic tests for N1, N2 (all three stamp formats),
   N3, N4, N5 and the migration backfill. No existing test weakened.
2. Extend `eval/consolidation_repro.py` with the N1 scenario (single May / married Jun / single Jul
   in one batch) and an N2 scenario using a LoCoMo-style stamp; show pass 1 converging and pass 2
   being a no-op.
3. A live end-to-end run on **both** local endpoints — `http://127.0.0.1:8460/v1` (`glm-5.3-flash`)
   and `http://<lan-node>:8889/v1` (`local-judge`, a second local inference node) — ingesting the same small
   capture set twice (once per endpoint, separate DBs), then `compile` and `consolidate` twice.
   Paste the actual output. The point is to show consolidation is correct with a second model's
   extraction, not just GLM's.

## Deliverables

`reports/phase15-report.md` with the diff summary, the measured before/after numbers for N2's
mis-ordering count and N4's flag audit, the repro output, both live runs, and anything unverified.
