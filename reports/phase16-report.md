# Phase 16 — N7–N11 from `reports/tes-review-3.md`

Author: Polly (coordinator; implementation by a local OMP worker on the `ms-glm` route,
`127.0.0.1:8460`, plus direct edits by Polly). Base commit: `d73b6ae`. Date: 2026-11-07.

This pass closes the five defects left open by Tes's third review. It is **not** DS-dependent: no call
went to the Spark pair's `:8889` route.

## Test evidence

| | Command | Result |
|---|---|---|
| Before (pristine `d73b6ae` worktree, gitignored dogfood inputs copied in) | `.venv/bin/python -m pytest -q` | **115 passed** |
| Before, phase-16 tests only | `.venv/bin/python -m pytest tests/test_phase16.py -q` | **15 failed, 3 passed** |
| After | `.venv/bin/python -m pytest -q` | **133 passed** |

Correction to the card: the suite at `d73b6ae` is **115 passed**, not 113. The 113 figure omits two
tests that only run when the gitignored `eval/dogfood/session.db` and
`eval/dogfood/redaction_rules.local.json` are present; in a fresh worktree without them the same tree
reports 114 passed + 1 skipped (`tests/test_quote_integrity.py`). Both figures were measured today.

18 tests were added in `tests/test_phase16.py`. **15 of them fail at `d73b6ae` and pass after the fix.**
The 3 that already passed are deliberate guard tests (they assert that the fix does *not* over-fire):

- `test_n9_parseable_captured_at_is_silent` — an explicit parseable stamp must not warn.
- `test_n11_event_not_flagged_against_a_later_state` — no advisory flag on an event/state pair.
- `test_n8_event_vs_state_pair_is_not_a_brief_contradiction` — no contradiction note for that pair.

Per defect (fails before → passes after): N7 four tests (tenure paraphrase supersession, child-count
key collapse, occupation slot key, numeric key without phrasing fragments); N8 four (Earlier follows
the capture stamp, resolved pair not labelled, event-vs-state not labelled, uncomparable stamps say
`Unresolved`); N9 six (undated capture loses to dated history, `captured_at_explicit` written,
legacy-database migration keeps a usable stamp, ingest warns without a stamp, ingest warns on an
unparseable stamp, parseable stamp is silent); N10 two (halt rolls back the whole pass and the next
pass halts again; CLI exits non-zero and applies nothing); N11 two (spouse/state retired by a later
"single" while the marriage event stays active; event not flagged).

## What changed

### N7 — slot keys no longer carry extractor phrasing (`src/cairnstone/compile.py`)

- `_VALUE_RE`: month names are now explicit optional-suffix alternations with word boundaries, so
  `married` is no longer read as `mar`+`ried` while `Mar 31` still matches.
- `_canonical_slot_key` (new): residual keys keep only `[a-z0-9']+` tokens, drop possessive `'s`,
  drop the boilerplate copula/auxiliary/time-adverb set, and fold plurals (irregular map plus a
  trailing-`s` rule for tokens ≥ 4 chars not ending `ss`/`us`/`is`).
- `_subject_prefix`: strips the extra article/work/role tails and a possessive `'s`. `plans`, `to`
  and `become` are deliberately **not** stripped, so a plan stays a distinct slot from a status.
- The occupation branch now runs its captured subject through `_subject_prefix`.

Measured against the exact strings in `tes-review-3.md` (probe run, not asserted from memory):

```
"Caroline has been working as a nurse for 4 years as of 2023-05-08." -> [('caroline nurse year', ('4','2023','05','08')), ('cat:occupation:caroline', ('nurse',))]
"Caroline has been a nurse for 5 years."                             -> [('caroline nurse year', ('5',))]
"Caroline has 1 child."                                             -> [('caroline child', ('1',))]
"Caroline has 2 children."                                          -> [('caroline child', ('2',))]
"Caroline's spouse is Tomas"                                        -> [('caroline spouse toma', None), ('cat:relationship_status:caroline', 'married')]
```

### N8 — contradiction notes (`src/cairnstone/retrieve.py`)

`_contradiction_notes(selected, stamps)` now: considers only `active` facts on the same page that
share a slot key with different values; skips pairs where exactly one side is an event fact; orders
by parsed capture stamp so the genuinely older fact is labelled `Earlier`; emits
`Unresolved: <a> (contradicts <b>, capture times not comparable)` when either stamp is missing or
unparseable, or the two are identical; emits each fact-id pair once; sorts notes by
`(older stamp, older fact id, newer fact id)`. `build_brief` passes the capture stamp map through a
new `_capture_stamps(conn)` helper. The docstring's old "newest first" claim is corrected.

### N9 — missing/unparseable stamps (`src/cairnstone/store.py`, `src/cairnstone/cli.py`, `compile.py`)

- `captures.captured_at_explicit` added (schema + migration). `store.add_capture` writes `1` only
  when the caller supplied a stamp that `parse_timestamp` can read, else `0`.
- `cairnstone ingest` warns on **stderr** for a missing `--captured-at` and for an unparseable one,
  storing the raw text as before and still exiting 0 (verified live).
- `compile._capture_clocks(conn, brain_id)` returns `(known, stamp, capture_id)` per capture; `dedupe`
  and `_supersede_contradictions` order on that tuple, so a dated fact beats an undated or
  unparseable one regardless of stored stamps, and the P6 equal-instant tie applies only when
  `known` and the stamp are both equal.

### N10 — P11 halt is a rollback (`compile.py`, `store.py`, `docs/compile-policies.md`)

`dedupe`, `_supersede_contradictions`, `_write_contradiction_flag` and `store.supersede_fact` take
`commit=True` (existing callers unchanged). `consolidate` runs the whole pass with `commit=False`,
then `conn.rollback()` before raising `PolicyHalt` when the rate is exceeded, otherwise
`conn.commit()`. `docs/compile-policies.md` P11 now states the pass is one transaction, a halt applies
nothing, and the next run re-attempts and halts again until reviewed.

### N11 — spouse slots and event history (`compile.py`)

- `_SPOUSE_RE` gives `^<subject>'s (spouse|husband|wife|partner) (is|was) <name>` a
  `cat:relationship_status:<subject>` slot with the documented inference `married` (or `partnered`
  for `partner`).
- `_is_event_fact` (bounded event-marker regex) is used by both the brief notes and the supersession
  pass. An older event is never superseded or flagged by a newer state; an event may still supersede
  an older state, and two events still supersede each other.
- The supersession pass now resolves **every** stale claim on a slot against the current truth, not
  only the last one seen, which is what lets "spouse is Tomas" and "is married" both retire behind a
  later "is single".

## Test rewrites (explicitly reported)

One existing assertion was rewritten, and only the one authorised by the phase-16 brief:
`tests/test_phase15.py::test_n6_phrasing_variant_relationship_contradicts` previously asserted that
the marriage **event** "Caroline got married in May 2023" was superseded by the later state
"Caroline is single now" — exactly the behaviour N11 reverses. It now asserts that both phrasings
reach the same `cat:relationship_status:caroline` slot (the N6 property it existed to protect), that
the event stays `active`, that the July re-assertion stays active, and that the stale May "single"
is not active canonical. Its docstring states why. No other existing assertion was weakened; the
phase-14 D6 test is untouched.

## Deviations from the brief, and why

1. The migration's column default is `1` and there is **no** conditional backfill: existing rows keep
   `1` as the brief specified. The first implementation had `DEFAULT 0` plus a backfill only for rows
   with a non-empty `captured_at_text`, which would have silently demoted every capture in a
   pre-phase-15 database (those rows have `captured_at_text IS NULL`) to "undated" — reintroducing
   N9 for existing data. `test_n9_legacy_rows_keep_a_usable_stamp` covers this.
2. The `Unresolved:` note branch was missing from the first implementation; it is now implemented and
   tested as the brief specified.

## What I did **not** verify

- **No model calls at all.** Every test is deterministic (`store.add_fact`, no network, fake
  embeddings). The N7 keying was checked on the literal strings from `tes-review-3.md` and on
  synthetic facts, **not** on a live DeepSeek extraction pass over real conversations. Whether the
  canonicalisation catches the phrasing DeepSeek actually emits is unverified.
- **No LoCoMo or LongMemEval re-measure at this HEAD.** README's "Measured results" row (78.0%,
  1,276 mean tokens, measured 2026-11-06) predates phases 15 and 16 and is now stale. The separate
  card `t_f480c1af` (Tes) covers the like-for-like re-measure; README's claim needs a further
  re-measure after these fixes before it is true as written.
- **The dogfood database was not re-consolidated.** The migration is covered by a synthetic legacy
  database, not by opening the real `eval/dogfood/session.db` and inspecting the resulting
  `captured_at_explicit` values or the supersession counts.
- **N7's singularisation is a heuristic.** It folds `children→child` correctly, but also turns
  `Tomas` into `toma` in the (non-operative) spouse subject slot. No false merge was observed in the
  suite, but it is not a linguistic guarantee.
- **N8's event detection is a bounded marker list**, per the brief. An event phrased outside that list
  ("eloped", "separated") is treated as a state.
- **The publish-guard push** is not part of this report's evidence until the push actually succeeds;
  see the task handoff.

## Files changed

`docs/compile-policies.md`, `src/cairnstone/cli.py`, `src/cairnstone/compile.py`,
`src/cairnstone/retrieve.py`, `src/cairnstone/store.py`, `tests/test_phase15.py` (authorised rewrite),
plus new `docs/phase16-brief.md` and `tests/test_phase16.py`.
