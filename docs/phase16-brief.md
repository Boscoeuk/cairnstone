# Phase 16 — close N7–N11 from `reports/tes-review-3.md`

Source of truth: `reports/tes-review-3.md` (HEAD `d73b6ae`). Five defects remain. This brief states
the **decided design** for each; implement it, do not redesign it. If a decision looks wrong, stop
and say so in your final message rather than silently choosing another behaviour.

Constraints that do not move:

- Interpreter: `.venv/bin/python -m pytest -q`, run from the repository root. Bare `python3` is Xcode 3.9
  and fails collection. The suite is **115 passed** at `d73b6ae` (measured 2026-11-07; the earlier
  "113" omitted two tests that need the gitignored `eval/dogfood` inputs); it must stay green.
- Do **not** weaken an existing assertion. Two rewrites are authorised (listed below); any other
  rewrite must be justified in your final message.
- No model calls and no network in tests. Facts are written with `store.add_fact`, as in
  `tests/test_phase14.py` and `tests/test_phase15.py`.
- Do not change extraction prompts, retrieval ranking, `eval/harness.py`, the citation invariant
  (`quote == captures.content[span_start:span_end]`), or any measured number.
- Do not commit. Polly reviews the diff and commits.

Each fix needs a test that **fails at `d73b6ae`** and passes after. Put them in
`tests/test_phase16.py`, deterministic, one test per defect (several tests per defect is fine).

## N7 — slot keys must not carry extractor phrasing

Reproduced at `d73b6ae`:

```
"Caroline has been working as a nurse for 4 years as of 2023-05-08."
  -> key 'caroline has been working as a nurse for years as of - - .', value ('4','2023','05','08')
  -> occupation key 'cat:occupation:caroline has been'
"Caroline has been a nurse for 5 years."
  -> key 'caroline has been a nurse for years.', value ('5',)
"Caroline has 1 child."   -> key 'caroline has child.'
"Caroline has 2 children."-> key 'caroline has children.'
```

The two tenure facts never compare, so the stale value stays active; "1 child"/"2 children" key
differently (Tes measured X2 6/6 wrong).

Decided design — implement exactly this in `src/cairnstone/compile.py`:

1. **Month/day value regex.** `_VALUE_RE` currently matches month names as a prefix followed by
   `[a-z]*`, so `"Caroline is married"` yields the value token `married` (matched as `mar`+`ried`)
   and a key `'caroline is .'`. Replace the month alternation with explicit optional suffixes —
   `jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t|tember)?|oct(ober)?|nov(ember)?|dec(ember)?`
   — with word boundaries on both sides, so `married` is not a month and `Mar 31` still is.
2. **Canonical numeric key.** In `_split_subject_slot`, after removing value tokens, canonicalise the
   residual key:
   - keep only tokens matching `[a-z0-9']+` (this drops `-`, `.`, `,` fragments);
   - strip a trailing possessive `'s`;
   - drop these boilerplate tokens: `a an the is are was were be been being am has have had having
     as of for since during working now currently recently still also then later`;
   - singularise: irregular map `children→child, people→person, men→man, women→woman, feet→foot,
     teeth→tooth, mice→mouse`; otherwise strip a trailing `s` from tokens of length ≥ 4 that do not
     end in `ss`, `us` or `is`;
   - join with single spaces; if nothing remains, return `(None, values)` as today.
   Result: both tenure facts key as `caroline nurse year` with different values, and
   `1 child`/`2 children` both key as `caroline child` with values `('1',)`/`('2',)`.
3. **`_subject_prefix`.** Strip trailing tokens in `_COPULA_TAIL` as today, plus `a an the working
   work works spouse husband wife partner`, and strip a possessive `'s` from the final token. It must
   NOT strip `plans`, `to` or `become` — `test_plan_fact_does_not_contradict_status_fact` depends on
   "caroline plans to become" staying distinct from "caroline".
4. **Occupation subject.** The occupation branch of `_fact_slots` must run the captured subject
   through `_subject_prefix`, so `"Caroline has been working as a nurse…"` keys
   `cat:occupation:caroline`, not `cat:occupation:caroline has been`.

## N8 — `_contradiction_notes` direction and scope

At `d73b6ae` the notes walk `selected` (score/fact-id order) and label the *newer* fact "Earlier".
Decided design for `retrieve._contradiction_notes`:

- Signature becomes `_contradiction_notes(selected, stamps)`; `build_brief` builds
  `stamps = {r["id"]: r["captured_at"] for r in conn.execute("SELECT id, captured_at FROM captures")}`
  and passes it. Do not add columns to the public dicts returned by `build_brief`.
- Consider only facts with `status == "active"` (a pair resolved by supersession is not a live
  contradiction), on the same page, sharing a slot key with different values.
- Skip a pair when exactly one side is an event fact (see below) — an event and a state are not a
  contradiction. Two events or two states may be.
- Order by capture stamp: the side with the **earlier** `captured_at` is "Earlier". Emit
  `Earlier: <older text> (contradicts <newer text>)`.
- When the pair cannot be ordered (equal stamps, or either capture has no parseable stamp), emit
  `Unresolved: <a text> (contradicts <b text>, capture times not comparable)`.
- Deterministic order: sort notes by `(older capture stamp or "", older fact id, newer fact id)`, and
  emit each fact-id pair once.
- Fix the docstring: it currently claims "newest first".

Event detection: add `_is_event_fact(text)` in `compile.py`, a bounded marker regex —
`moved|moves|moving|migrated|arrived|departed|left|joined|started|began|stopped|quit|resigned|graduated|visited|travelled|traveled|bought|sold|got married|married on|got divorced|divorced on|split up|split from|broke up|met|was born|died`
— used for brief notes and for the N11 supersession rule below.

## N9 — missing or unparseable stamps must be visible and must not win

1. `cairnstone ingest` without `--captured-at` prints a warning on **stderr** naming the stamp it
   inferred, and still exits 0.
2. `--captured-at` that `store.parse_timestamp` cannot parse prints a warning on stderr, still stores
   the raw text (as today), and still exits 0.
3. An undated capture must not beat dated history. Add `captures.captured_at_explicit INTEGER NOT
   NULL DEFAULT 1` in `init_db`'s migration block (same pattern as `compiled_at` /
   `captured_at_text`). `store.add_capture` writes `0` when `captured_at is None` and `1` otherwise.
   Existing rows keep `1` — their stored stamp is the best evidence available.
4. In `compile.py`, add `_capture_clocks(conn, brain_id)` returning `{capture_id: (known, stamp,
   capture_id)}` where `known = 1` only when `captured_at_explicit = 1` **and**
   `store.parse_timestamp(captured_at)` is not None. Use that ordering tuple — `(known, stamp,
   capture_id)` — in `dedupe` (canonical choice) and in `_supersede_contradictions` (both the
   per-fact clock and the duplicate-cluster latest clock). Consequences to implement exactly:
   - a dated fact beats an undated/unparseable one regardless of stored stamps;
   - two undated captures still order by ingest stamp (this keeps `test_single_vs_married…` and
     `test_contradiction_superseded`, which use undated captures, green);
   - the equal-instant tie test (P6) applies only when `known` is equal and stamps are equal.

## N10 — a P11 halt must not leave the mutations committed

`docs/compile-policies.md` P11 says a pass over `max_mutation_rate` "is halted for review". Today the
mutations are committed first and then `PolicyHalt` is raised, so the next run reports zeros and the
halted pass silently becomes permanent.

Decided design: apply the pass in one transaction and roll it back on halt.

- Add `commit=True` keyword parameters to `dedupe`, `_supersede_contradictions`,
  `_write_contradiction_flag` and `store.supersede_fact`; all existing callers keep the default
  behaviour.
- `consolidate(...)` calls them with `commit=False`, then:
  - if `max_mutation_rate` is exceeded: `conn.rollback()`, then raise `PolicyHalt` whose message says
    the pass was rolled back and nothing was applied;
  - otherwise `conn.commit()` and return the counts.
- `cli.cmd_consolidate` already turns `PolicyHalt` into `CliError`; confirm the message reaches
  stderr and the exit code is non-zero, and add a CLI test for it.
- Update the P11 paragraph in `docs/compile-policies.md` to say the pass is one transaction, a halt
  rolls it back with nothing applied, and the next run re-attempts and halts again until reviewed.

## N11 — spouse facts are relationship slots; events are history

At `d73b6ae`, after "split up / single again": "Caroline's spouse is Tomas" stays active because it
forms no slot at all, and the historical marriage event is superseded as if it were a state.

Decided design:

1. **Spouse coverage.** A new regex in `_fact_slots` for
   `^<subject>'s (spouse|husband|wife|partner) (is|was) <name>` emits
   `cat:relationship_status:<subject>` with value `married` for spouse/husband/wife and `partnered`
   for partner. Documented inference: a spouse implies married. This makes "spouse is Tomas" compare
   equal to a same-time "is married" (no false flag) and lose to a later "is single".
2. **Event history.** In `_supersede_contradictions`, when the older row is an event fact and the
   newer row is a state fact, do not supersede and do not flag: the event stays active as history.
   An event **may** still supersede an older state (a divorce event retires "is married"), and two
   events on the same slot supersede each other normally.
3. **Authorised test rewrite.** `tests/test_phase15.py::test_n6_phrasing_variant_relationship_contradicts`
   asserts that the event "Caroline got married in May 2023" is superseded by the later state
   "Caroline is single now". That assertion is exactly what N11 reverses. Rewrite it to assert:
   - `_fact_slots("Caroline got married in May 2023")` and `_fact_slots("Caroline is single now")`
     share the `cat:relationship_status:caroline` key (this is the N6 fix it was written for);
   - the marriage event remains `active`;
   - the May "single" fact is not active canonical (it is a duplicate of the July re-assertion).
   Keep the docstring honest about why it changed. Say so in your final message — Polly must report
   the rewrite explicitly.

## What to run before you report

```
cd cairnstone
.venv/bin/python -m pytest -q
```

Iterate until the whole suite is green. Report: the final pass count, the tests you added, the two
authorised rewrites, and anything you could not verify. Do not commit and do not write
`reports/phase16-report.md` — Polly does both.
