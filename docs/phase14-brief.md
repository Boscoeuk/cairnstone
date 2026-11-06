# Phase 14 — make the nightly consolidation pass real

`reports/tes-consolidation-1.md` is the specification. Read it first. It exercises the shipped
consolidation path and finds six defects. Fix them at the root, in code, with tests that would have
caught each one.

Do not change extraction behaviour, retrieval ranking, the eval harness or any measured number.
Do not weaken the citation invariant: every fact keeps `quote == captures.content[span_start:span_end]`.

## Defects to fix

**D1 — a stale canonical fact survives a pass.** `supersede_contradictions` selects active rows
without excluding `duplicate_of`, so a duplicate row replaces the canonical fact in the `seen` map
and the canonical fact is never compared with the new claim. A single pass leaves the brain
contradictory, and a second pass mutates it. Fix: resolve every active fact to its canonical row
before comparing (or restrict the scan to `duplicate_of IS NULL`), so one pass converges.

**D2 — `cairnstone compile` re-extracts every capture on every run.** `cmd_compile` selects all
captures each time; nothing records what was already compiled. Every nightly run duplicates every
fact and spends a model call per historical capture. Fix: record compilation state per capture
(a `compiled_at` column on `captures`, or a `compile_runs`/`compiled_captures` table), have
`compile` process only uncompiled captures, and add a separate `consolidate` CLI command that runs
`dedupe` + `supersede_contradictions` (+ contradiction flagging, below) over the whole brain
without touching the model. That command is the nightly entry point the README promises.

**D3 — "newer" is a higher capture id, not a later `captured_at`.** Backfilled or out-of-order
imports invert supersession. Fix: order by `captures.captured_at` then id. A fact with an unknown
timestamp must not silently win; decide and document the tie-break.

**D4 — the swap path records the wrong value.** Around `compile.py:536-543`, when
`new.capture_id < old.capture_id` the rows swap but `seen[key] = (value, new)` stores the current
row's value against the other row, so the next same-capture fact is judged a contradiction of
itself. Real consequence in scenario A: "Caroline is married" was superseded by its own
re-extracted duplicate, and because the survivor was marked `duplicate_of`, the claim disappeared
from briefs and export entirely. Fix the swap so the stored value and stored row agree. Add a
regression test with fact ids out of capture order, and one asserting that a fact is never
superseded by a duplicate of itself.

**D5 — contradiction detection only covers numbers/dates and a six-word relationship lexicon.**
Location, occupation and free-text values are never compared, and a numeric slot only matches when
the model words both facts identically. Fix in two parts:
(a) extend slot extraction with a small lexicon for location ("lives in", "moved to"), occupation
("works as", "is a"), and relationship status; compare the extracted value, not the whole sentence;
(b) when a slot matches but values differ and the code cannot decide, write a
`fact.contradiction_flagged` change event so the contradiction is visible instead of silently
active. Keep the flag advisory: do not retract either fact on a flag.

**D6 — retrieval's near-duplicate collapse keeps the stale side.** `select_facts` clusters by
Jaccard >= 0.5 and keeps the earliest id, so "lives in Berlin" and "lives in Lisbon" collapse and
the older one is served. Fix: when a cluster's members disagree on the slot value, prefer the fact
from the latest `captured_at` (fall back to id). Add a test that a brief for "Where does Caroline
live?" returns Lisbon after the move.

**Near-duplicate detection** is exact-text only, so "favourite" and "favorite" are not linked. Fix
with a normalised claim key (case, punctuation, common British/American spelling variants).

## Tests

Add deterministic tests (no model) that reproduce each scenario in `reports/tes-consolidation-1.md`
§Defects. At minimum: D1 two-pass convergence, D3 out-of-order captures, D4 self-supersede and
wrong-direction supersede, D5 location contradiction flag, D6 stale-side retrieval, spelling-variant
duplicate linking, and a test that `consolidate` is idempotent on a clean brain (second run changes
nothing).

## Acceptance

- `python3 -m pytest -q` green, with the new tests.
- A deterministic script under `eval/` (no model) that builds Tes's scenario B/C/D and prints the
  fact table after one and two consolidation passes, proving D1/D3/D4 are fixed.
- A live smoke: 2 captures compiled, `consolidate` run twice, second run reports no changes.
- `reports/phase14-report.md`: what changed, the new command's usage, test counts, the smoke output,
  and anything not verified.

## Boundaries

Local endpoints only. Do not modify `eval/harness.py`, `eval/dogfood/`, `eval/longmemeval/`.
