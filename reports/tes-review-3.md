# Tes review 3: phase 15 (N1–N5) verification + consolidation with a non-GLM extractor

Card: t_e0355fe7 (supersedes t_26e6535b). Author: Tes. Date: 2026-11-07.

**Code under test: `4c36e19`.** History moved again after Polly's comment. The reflog shows `filter-branch: rewrite` at 14:47:53, turning `1761243` into `4c36e19` (phase 15 is now `eaa88e8`, previously `9e8191f`). The rewrite touched 14 docs, logs and report files and **no code**: `git diff 1761243 4c36e19 -- src tests eval/harness.py eval/measure_timestamp_order.py` is empty.

I ran the live model run at `a2b5340`. I re-ran every deterministic harness at `4c36e19` (`det-`, `tie-`, `n3p11-` and `locomo-4c36e19.out`, using fresh `.backup` copies in `h4c/`). Apart from temp-dir names and timestamps, the output is identical to the `a2b5340` runs. `locomo-a2b5340.err` (an `IndexError` on an empty `rows`) comes from an earlier invocation pointed at a wrong path. The matching `.out` and the `4c36e19` re-run are complete.

**Tests.** At `4c36e19`, `.venv/bin/python -m pytest -q` gives `113 passed in 4.97s`.

**What I wrote.** This file is the only thing I wrote to the repo. The harnesses and raw outputs are in Tes's local scratch directory:
- `spark.py` → `spark-a2b5340.out`
- `locomo3.py` → `locomo-a2b5340.out`
- `r2/det.py`, `r2/tie.py`, `r2/brief.py` → `*-a2b5340.out`. These are review 2's harnesses, copied unchanged.
- `n3p11.py` → `n3p11.out`
- `cli5/`
- The `a7bb5b0` baselines are `baseline-a7bb5b0.out` and `locomo-baseline.out`.

**Which model did the extraction.** The second local route (the Spark-side endpoint, port 8889) is
**not the same machine as the GLM route**. It is the Spark pair. At 14:44Z its `backend.json` said:
`DeepSeek-V4.1-Flash-1017 EXL3 EAQ v1 2.9bpw ...`, served by `tensorfold-native` on port 8898. Both
nights' extraction calls succeeded, before the DS upgrade outage. So this is the first consolidation
run where a model other than GLM did the extraction, but the model was DeepSeek-V4.1-Flash, not
anything on the Spark itself.

**Data copies.** Every DB was copied with `sqlite3 "file:…?mode=ro" ".backup"` (`immutable=1` for dogfood).

## Verdicts

| Defect | Verdict | Evidence |
|---|---|---|
| N1: a re-assertion is hidden as a duplicate | **Fixed** | X1a (one batch: single May / married Jun / single Jul): married `superseded sup_by=3`, July single canonical. X1c gives the same result; X1b is correct; pass 2 is all zeros. Live Spark run: final state has married f9 superseded by July single f14. |
| N2: stamps compared as strings | **Fixed** | Stamp-pair mis-ordering on conv-26 went **81/171 → 0/171**; on conv-30, **79/171 → 0/171** (no unparseable stamps). X3c (LoCoMo-format stamps): single superseded by married, which is correct. Live: three stamp formats are stored as ISO (`2023-06-10T17:50:00+00:00`, original kept in `captured_at_text`), and July single wins. At `a7bb5b0` the same run left married winning. |
| N3: a flagged fact vanishes from the brief | **Partially fixed.** Both sides are now visible, but the "Earlier:" marker is **wrong way round** (N8) | Brief text below. |
| N4: false-positive flags | **Partially fixed.** 17 → 3 flags, but **all 3 remaining are false** | Audit below. Location trailing words are fixed: X5 has 0 flags. Live, "Lisbon for work" / "near the old canal" give 1 flag where `a7bb5b0` gave 3 spurious ones. |
| N5: equal timestamps / missing stamps | **Partially fixed** | P6 is honoured: `tie.py` flags, both rows stay `active`, nothing is superseded. `ingest --captured-at` exists and parses LoCoMo stamps. What is not fixed is in N9: no warning, unparseable input stored silently, and an undated API capture still becomes "now" and wins (X3a: married 2023-06 is superseded by an undated backfill). |
| N6 (Polly, found live): categorical key took the text before the value | **Fixed for the reported case** | `_fact_slots("Caroline got married on 2023-06-10.")` returns `cat:relationship_status:caroline`, the same key as "Caroline is single.". The incomplete stripping is N7. |

**Phase-14 test edits (were assertions weakened?).** No. The equal-timestamp test now asserts more than before: both rows `active`, both `superseded_by` NULL, and exactly 1 flag event. The D1 and spelling tests swap which row is canonical and keep the same number of assertions. One D6 assertion was inverted deliberately, from "Berlin absent" to "Berlin present and `contradict` in the brief". Nothing in those tests checks the marker's direction, which is why N8 passes.

**P11.** A halt is implemented and fires. `n3p11.py` printed `PolicyHalt … mutated 10 of 9 active facts (111.1%) … halted for review`. The count of 10 for 9 facts is my harness's fault: digits in subject names created numeric-slot flags. The real problem is that the mutations were already committed (see N10). `/health` backoff exists in `cli._health_backoff`. Its behaviour under load is **unverified**.

## Item 1: the Spark run (real output, trimmed; full text in `spark-a2b5340.out`)

```
db: <scratch>/spark.db endpoint: http://<lan-node>:8889/v1 local-judge
##### NIGHT 1 (May + June)
  stored stamps: [(1, '2023-05-08T13:56:00+00:00', '1:56 pm on 8 May, 2023'), (2, '2023-05-08T14:10:00+00:00', '2:10 pm on 8 May, 2023'), (3, '2023-06-10T17:50:00+00:00', '2023/06/10 (Sat) 17:50'), (4, '2023-06-10T18:05:00+00:00', '2023/06/10 (Sat) 18:05')]
  compile_all(n1) -> {'captures': 4, 'failed_captures': [], 'facts_accepted': 12, 'facts_rejected': [(3, 'Tomas is from Lisbon.', "subject_unresolved: …"), (4, 'Caroline is at the hospital as of 2023-06-10.', 'weak_quote: …')], 'duplicates_linked': 0, 'superseded': 1} in 19.7s; telemetry={'engine': 'lanes', 'tokens_per_second': 52.4, …}
  $ cairnstone compile      -> rc=0  ok: compiled captures=0 accepted=0 rejected=0 duplicates_linked=0 superseded=0 failed_captures=[]
  $ cairnstone consolidate  -> rc=0  ok: consolidated duplicates_linked=0 superseded=0 flagged=0
  $ cairnstone consolidate  -> rc=0  ok: consolidated duplicates_linked=0 superseded=0 flagged=0
##### NIGHT 2 (July)
  stored stamps: [(5, '2023-07-15T09:00:00+00:00', '2023-07-15T09:00:00+00:00')]
  compile_all(n2) -> {'captures': 1, 'failed_captures': [], 'facts_accepted': 3, 'facts_rejected': [], 'duplicates_linked': 0, 'superseded': 1} in 5.3s
  $ cairnstone compile      -> rc=0  ok: compiled captures=0 accepted=0 rejected=0 duplicates_linked=0 superseded=1 failed_captures=[]
  $ cairnstone consolidate  -> rc=0  ok: consolidated duplicates_linked=0 superseded=0 flagged=0
  $ cairnstone consolidate  -> rc=0  ok: consolidated duplicates_linked=0 superseded=0 flagged=0
  -- final state after night 2 consolidate x2:
   f1   c1  2023-05-08T13:56  active     Caroline lives in Berlin, near the old canal.
   f2   c1  2023-05-08T13:56  superseded sup_by=9   Caroline is single.
   f3   c2  2023-05-08T14:10  active     Caroline works as a nurse.
   f4   c2  2023-05-08T14:10  active     Caroline has been working as a nurse for 4 years as of 2023-05-08.
   f5   c2  2023-05-08T14:10  active     Caroline's favourite hobby is painting landscapes.
   f6   c3  2023-06-10T17:50  active     Caroline moved to Lisbon during the week of 2023-06-05.
   f7   c3  2023-06-10T17:50  active     Caroline lives in Lisbon.
   f8   c3  2023-06-10T17:50  active     Caroline moved to Lisbon for work.
   f9   c3  2023-06-10T17:50  superseded sup_by=14  Caroline is married.
   f10  c3  2023-06-10T17:50  superseded sup_by=14  Caroline got married on 2023-06-10.
   f11  c3  2023-06-10T17:50  active     Caroline's spouse is Tomas.
   f12  c4  2023-06-10T18:05  active     Caroline has been a nurse for 5 years.
   f13  c5  2023-07-15T09:00  active     Caroline split up with Tomas.
   f14  c5  2023-07-15T09:00  active     Caroline is single.
   f15  c5  2023-07-15T09:00  active     Caroline is staying in Lisbon.
   ev7   fact.contradiction_flagged f1 {"contradicts": 6, "slot": "cat:location:caroline", "values": [["berlin"], ["lisbon"]]}
   ev8   fact.superseded      f2 {"superseded_by": 9}
   ev10  fact.superseded      f9 {"superseded_by": 14}
   ev11  fact.superseded      f10 {"superseded_by": 14}
```

**What worked.**
- The re-assertion sequence ends as single. Each step superseded the right fact, in true time order, across three stamp formats.
- Both nights' second `consolidate` is a no-op.
- `compile` with nothing new to extract makes no model call.

**What didn't.**
- f4 "4 years as of 2023-05-08" and f12 "5 years" are both still `active` (N7).
- Berlin is still `active` and only flagged. That is by design for advisory slots, but the brief then labels it the wrong way round (N8).
- f11 "spouse is Tomas" survives the split (N11).

## Item 2: before/after counts

| Measure | `a7bb5b0` | `a2b5340` / `1761243` |
|---|---|---|
| conv-26 distinct session-stamp pairs mis-ordered as stored | 81/171 | **0/171** |
| conv-30 | 79/171 | **0/171** |
| det.py X1a / X1c (N1) | wrong (married wins) | correct (single wins) |
| det.py X3c LoCoMo stamps (N2) | married superseded (wrong) | single superseded (correct) |
| tie.py equal instant (N5) | single superseded | flagged, neither superseded |
| det.py X5 false flags (lisbon/lisbon-husband, nurse/vegetarian/single mother) | 3 | 0 |
| det.py X2 numeric "1 child / 2 children / 3 children" | 6/6 wrong | **6/6 wrong, unchanged** (N7) |
| det.py X4 pronoun "She lives in Porto/Madrid" | flagged `cat:location:she` | unchanged |

My 171 denominators count distinct session-stamp pairs. Polly's `measure_timestamp_order.py` counts capture pairs (87,571 / 67,896), so the two sets of numbers are not comparable. Both show 0 after the fix.

## Item 3: brief text for a flagged contradiction (N3)

This is a deterministic case (`n3p11.py`): Berlin dated 2023-05-01, Lisbon dated 2023-06-01, location slot flagged. `build_brief("Where does Caroline live?")` gives, verbatim:

```
### Records
- Caroline lives in Berlin [capture 1, span 0:1]
- Caroline lives in Lisbon [capture 2, span 0:1]
Earlier: Caroline lives in Lisbon (contradicts Caroline lives in Berlin)
```

Both facts are now visible and the brief says they contradict, so N3 is no longer silent. But the marker calls **Lisbon (June) "Earlier"** and Berlin (May) the newer claim, which is backwards.

The live Spark briefs do the same:
- Every question gives `Earlier: Caroline lives in Lisbon. (contradicts Caroline lives in Berlin, near the old canal.)`, with Berlin listed first.
- The night-2 history brief prints `Earlier: Caroline is single. (contradicts Caroline is married.)`. Single is July and married is June.

The cause is in `_contradiction_notes`. Its docstring says "newest first", but it walks `selected`, which is in score/fact-id order, not time order (N8). It also emits notes for pairs that are already resolved by supersession, not only for flagged pairs.

## Item 4: flag audit (fresh copies, two `consolidate` passes each)

| DB | Flags at `a7bb5b0` | Flags now | Flag | True? |
|---|---|---|---|---|
| conv-26 | 8 | 1 | `cat:occupation:melanie` "Melanie is a mom" (6 Jul) vs "Melanie is a parent" (13 Sep) | **False.** Same fact in two words. Quotes: "why I love being a mom" / "being a parent worth it". |
| conv-30 | 5 | 1 | `cat:occupation:jon` "Jon is a dancer" (8 Feb) vs "Jon is a teacher (works with students)" (23 Mar) | **False.** Jon holds both at once. Quotes: "Dancing and running my biz" / "Seeing my students succeed". Occupation is treated as single-valued when it isn't. |
| dogfood `session.db` | 4 | 1 | `cat:relationship_status:caroline` "Caroline is married" (c137) vs "Caroline is single" (c117), both stamped 2026-11-05 | **False as a contradiction about the world.** Both facts were extracted from assistant meta-text about the test fixture ("'Caroline is single' is extracted"). P6 handled the equal stamps correctly (flag, no supersede). The real fault is upstream extraction. |

Pass 2 was all zeros on all three DBs, and there are 0 time-inverted supersessions.

Dogfood still carries 25 `fact.superseded` events written before this HEAD (this run's pass 1 added 0 supersedes). Some of them are wrong:
- ev554–556 chain phase 9 → 8 → 7 → 6 accuracy figures from one capture.
- ev577 supersedes the conv-26 fact count with the conv-30 one. The migration does not revisit old events. That is outside N1–N5, but it is visible in the dogfood brain.

## Item 5: README "nightly evolution"

README lines 6–7 say "A compile pass merges duplicates, supersedes stale facts, and flags contradictions without destroying history". Line 42 says `consolidate` is the "nightly pass". **Still partially supported.** Supported as written:
- "merges duplicates"
- "without destroying history"
- ordering by true time for all stamp formats tested

Still untrue:
1. **"nightly"**: nothing schedules it. `consolidate` is a manual command, and no cron, launchd job or scheduler exists in the repo.
2. **"supersedes stale facts"**: only when the extractor's wording matches the slot key. The real-extraction run left "nurse for 4 years" active next to "5 years", and number-of-children wording still fails 6/6 (N7).
3. **"flags contradictions"**: flags are written and now shown, but:
   - the brief labels the older side as newer (N8);
   - all 3 flags on real data are false;
   - a P11 halt reports "halted for review" after the mutations are already committed (N10).

## New defects

- **N7 (correctness, reproduced live with the non-GLM extractor).** Slot keys still include the extractor's phrasing:
  - The numeric key for "Caroline has been working as a nurse for 4 years as of 2023-05-08." is `caroline has been working as a nurse for years as of - - .` with value `('4','2023','05','08')`. "…a nurse for 5 years." keys as `caroline has been a nurse for years.`, so the two never compare and the stale value stays active.
  - `_subject_prefix` doesn't strip "has been working as": occupation keys as `cat:occupation:caroline has been`, not `caroline`.
  - "1 child" / "2 children" still key differently (X2 6/6 wrong).
  - DeepSeek appends "as of <date>" routinely, so this will happen often.
- **N8 (product, misleading).** `_contradiction_notes` assigns "Earlier"/"contradicts" by position in `selected`, not by `captured_at`. In the brief text above the newer fact is called "Earlier". It also fires for resolved (superseded) pairs, and for event-vs-state pairs such as "moved to Lisbon" vs "lives in Berlin". The new D6 test only checks for the substring `contradict`, so this passes the suite.
- **N9 (N5 remainder).** Three gaps around missing or bad stamps:
  - `cairnstone ingest` without `--captured-at` prints nothing on stderr (checked with `2>file`: empty). The "explicit warning" in the phase-15 report exists only in the `--help` text. That is accurate, but the user who forgets the flag never sees it.
  - `--captured-at "next tuesday"` exits 0, prints no warning, and stores `captured_at='next tuesday'` raw. Policy says unparseable stamps go to stderr. How such a row then orders against ISO stamps is **unverified**.
  - `store.add_capture(…, None)` still becomes "now", so an undated backfill beats dated history (X3a).
- **N10 (P11 semantics).** `consolidate(max_mutation_rate=…)` applies and commits every mutation, then raises `PolicyHalt`. The docstring admits this ("a loud stop, not a rollback"). After the halt, the next run reports `superseded=0 flagged=0`, so the halted pass's mutations become permanent without review. P11 in `docs/compile-policies.md` says a run over the limit "is halted for review". A dry-run count before applying, or one transaction rolled back on halt, would make that true.
- **N11 (minor, slot coverage).** After "split up / single again", "Caroline's spouse is Tomas" stays active, and the event "Caroline got married on 2023-06-10" (still historically true) is superseded as if it were a state. The brief for "Is Caroline married?" therefore contains both "spouse is Tomas" and "is single".

## Not verified

- LoCoMo / LongMemEval scores at this HEAD (I didn't re-run them). The 78.0% figure belongs to the previous commit.
- How the `/health` backoff behaves under real load.
- How a row with an unparseable stored `captured_at` orders in supersession.
- The live `:8889` extraction run at `4c36e19` itself. It ran at `a2b5340`, and the code is identical, but model output is not deterministic. I did not repeat it, to keep load off the pair during the t_7d32adc9 upgrade window.
- Anything on any extraction route other than the one named above.
