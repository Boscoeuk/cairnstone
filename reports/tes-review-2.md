# Tes review 2: re-review of the phase 14 consolidation fixes (D1–D6)

Card: t_c4b62195. Author: Tes. Date: 2026-11-06. Code under test: HEAD `a7bb5b0` (the working tree's `src/` matches HEAD).
The specification is `reports/tes-consolidation-1.md`. I did not use or trust `eval/consolidation_repro.py`.
This file is the only thing I wrote to the repo. The harnesses and outputs are outside it, in
Tes's local scratch directory:
- `det.py` / `det.out`: deterministic consolidation scenarios.
- `brief.py` / `brief.out`: briefs.
- `nonet.py`: CLI with sockets disabled.
- `count_compile.py`: what `compile` would extract.
- `locomo.py`: real LoCoMo DB copies.
- `tie.py`: equal timestamps.
- `mig/`: copies of `eval/dogfood/session.db` and the conv-26/conv-30 DBs, taken with `sqlite3 ... ?mode=ro ".backup"`.

No chat model was called. Briefs used only the local nomic embeddings on `127.0.0.1:1234`.
`uv run --offline pytest -q` gives `104 passed in 39.04s`.

## Verdict per defect

| Defect | Verdict | Evidence (short; full output in `det.out` / `brief.out`) |
|---|---|---|
| D1 a duplicate hides a contradiction from the canonical fact | **Fixed** for the reported case. A related new defect is N1 | B1: pass1 `{'duplicates_linked': 1, 'superseded': 1, 'flagged': 0}`, pass2 all zero. Rows: f1 single `superseded sup_by=3`, f2 single `active dup_of=1`, f3 married `active`. |
| D2 `compile` re-extracts everything | **Partially fixed.** Fixed on new DBs, **not fixed on existing DBs** | New DB: your check stands. Existing DB: see item 5. All 366 captures would be re-extracted. |
| D3 "newer" means capture id | **Partially fixed.** Correct for ISO stamps; **wrong for the stamps the LoCoMo harness actually stores** (N2) | B3: f2 "4 years" (2023-05) `superseded sup_by=1`, f1 "5 years" (2023-06) active. X2: all 6 ingestion permutations of single/married/divorced end with only "divorced" active. On conv-26, 81 of 171 session-stamp pairs sort wrongly as strings. |
| D4 the swap stores the wrong value / a fact supersedes its own duplicate | **Fixed** | C1 and D4: one supersede only, f2 single → f1. Both "married" and "married and happy" stay active. No self-supersede. Pass2 is all zero. |
| D5 no location/occupation slots, no flag | **Partially fixed.** Slots and an idempotent flag exist, but the occupation slot gives mostly false positives (N4) | Berlin/Lisbon: `fact.contradiction_flagged` with values `[["berlin"],["lisbon"]]`, both active. Real data: all 4 flags on dogfood and all 13 on LoCoMo conv-26/30 are false (identity sentences like "X is a …"). |
| D6 retrieval serves the stale side | **Fixed as I specified it.** But it **hides the older flagged fact entirely** (item 4, N3), and it inherits N2 | "Where does Caroline live?" → `[(2, 'Caroline lives in Lisbon')]`. With LoCoMo-format stamps → `[(1, 'Caroline lives in Berlin')]`, the stale side. |

## The requested checks

**1. Re-runs (B1, B3, C1, D4).** The table above covers them. All four now give the correct state in one pass, and the second pass is a no-op.

**2. Break attempts.**
- *A duplicate of a fact that is later contradicted.* This **breaks** it (N1). I ran X1a in one batch: single (May), married (Jun), single (Jul). Truth: single.
  ```
  pass1 {'duplicates_linked': 1, 'superseded': 1, 'flagged': 0}
  f1 Caroline is single  c1 superseded sup_by=2
  f2 Caroline is married c2 active
  f3 Caroline is single  c3 active dup_of=1      <- the latest claim, hidden as a duplicate
  ```
  The July re-assertion is linked as a duplicate of the May fact. The contradiction scan then sees only the canonical fact and its May timestamp, so "married" wins. Briefs and export drop duplicates, so the brain says "married". X1c (single May, single Jul ingested 2nd, married Jun) gives the same wrong result.

  If consolidation runs between the batches (X1b), the result is correct: married `sup_by=3`, single c3 active. So the failure needs the re-assertion and the contradiction to land in the same compile/consolidate run. A first import or backfill of history does exactly that.
- *Three captures out of order.* **Holds** for the categorical slot and for same-wording numeric slots (6/6 permutations each).

  "1 child / 2 children / 3 children" leaves "1 child" active in every permutation. The cause is singular/plural wording (a D5-class key miss), not ordering: 2 → 3 is superseded correctly.
- *No captured_at.* `add_capture(..., None)` and `""` both store `_now()` (`2026-11-06T22:38:11…+00:00`). X3a is a backfilled "single" with no date against "married" dated 2023-06-01: **"married" is superseded by the undated backfill.**

  The docstring says "a capture with no timestamp cannot occur (the column is NOT NULL)". That is true of the column, but the API silently replaces a missing time with the ingest time. `cairnstone ingest` has no `--captured-at` option, so every CLI capture is dated at ingest time, and a CLI backfill always counts as newest.
- *Two people on one page.* **Holds.** The slot key includes the subject prefix. "Melanie lives in Berlin" / "Caroline lives in Lisbon", "Melanie is single" / "Caroline is married" and "Melanie has 2 kids" / "Caroline has 3 kids" produce no supersede and no flag. "Caroline's sister lives in Rome" is untouched.

  The one hit is pronouns: "She lives in Porto" / "She lives in Madrid" flags (`cat:location:she`). Being advisory, it is harmless here. A pronoun subject on a non-advisory slot would supersede.
- *Equal timestamps.* `tie.py` used two captures both at `2023-06-01T10:00:00+00:00`: "single" was **superseded** by "married" on capture-id order.

  `docs/compile-policies.md` P6 says equal timestamps must be **flagged, with neither superseded**. The code now documents the opposite (N5).

**3. `consolidate` never calls the model.** **Confirmed.** I set `CAIRNSTONE_BASE_URL` and `CAIRN_BASE_URL` to `http://127.0.0.1:9/v1` (dead) and also replaced `socket.connect`, `create_connection` and `getaddrinfo` with functions that raise:
```
ok: consolidated duplicates_linked=6 superseded=1 flagged=4   rc=0  real 0.11
ok: consolidated duplicates_linked=0 superseded=0 flagged=0   rc=0  real 0.11
```
That was on a copy of the dogfood DB. The second run is a no-op.

**4. Do flagged contradictions stay visible?** **No (N3).** Berlin (May) and Lisbon (Jun) are both `active` with a flag event, but the brief keeps only one of them for every phrasing:
```
'Where does Caroline live?'        -> [(2, 'Caroline lives in Lisbon')]
'Where did Caroline used to live?' -> [(2, 'Caroline lives in Lisbon')]
'Has Caroline lived in Berlin?'    -> [(2, 'Caroline lives in Lisbon')]
```
The brief text contains no flag or contradiction marker, and the occupation case behaves the same way. A genuine supersede behaves better: "Is Caroline married?" → married only, and the history question "Was Caroline single before?" → both. The net effect is that a flagged (unresolved) fact is hidden *more* than a superseded one, because history mode cannot recover it. The D6 collapse drops it whenever the cluster disagrees.

**5. Migration on an existing DB.** The migration is **safe but incomplete; D2 is not fixed for existing brains.**
- On a `.backup` copy of `eval/dogfood/session.db`, opening with HEAD added `7|compiled_at|TEXT|0||0`. Nothing else changed and nothing failed.
- After migration, `total=366 uncompiled=366 with_facts=306`. No backfill marks the 306 captures that already have facts as compiled.
- `cairnstone compile` with a dead port exits `error: local endpoint … unreachable`. It only checks the endpoint when the uncompiled list is non-empty.
- With the model stubbed out (`count_compile.py`), it reports `compile would extract 366 captures`.

So the first `compile` after upgrading re-extracts all 366 captures, about 1,640 facts' worth of model calls, which reproduces the original D2 defect once. The fix is a one-line backfill in the migration: `UPDATE captures SET compiled_at = <now> WHERE compiled_at IS NULL AND id IN (SELECT capture_id FROM facts)`. Whether captures that produced zero facts should also be marked is the owner's call.

**6. README "nightly evolution".** See the verdict below.

## New defects

- **N1 (correctness).** Dedupe makes the lowest fact id canonical, and the contradiction scan reads only the canonical fact's timestamp. A later re-assertion of an earlier value is therefore hidden as a duplicate, and an intermediate contradicting value wins (X1a, X1c). Fix: pick the canonical by latest `captured_at`, or give each canonical fact the latest timestamp among its duplicates when comparing.
- **N2 (correctness, affects the benchmark data).** `captured_at` is compared as a raw string in `_supersede_contradictions` and in the D6 winner (the chronological brief sort was already like this). `eval/harness.py` stores LoCoMo stamps such as `1:56 pm on 8 May, 2023`.
  - On conv-26, 81 of 171 session pairs order wrongly; on conv-30, 79 of 171.
  - On copies of those DBs, `consolidate` wrote 8 and 5 flags, of which 6 and 2 had old and new reversed in time. Examples: OLD `Caroline is an artist [14 August]` vs NEW `[20 July]`; OLD `Jon is a teacher [23 March]` vs NEW `Jon is a dancer [8 February]`.
  - X3c is a deterministic repro: single (`1:56 pm on 8 May, 2023`) and married (`1:14 pm on 25 May, 2023`) give **"married" superseded**.
  - Before phase 14, capture-id order was chronological for LoCoMo, so this is a regression there. Fix: normalise to ISO-8601 UTC at `add_capture`, or parse when comparing.
- **N3 (product).** Item 4: flagged facts disappear from briefs, and the flag is never shown to the reader.
- **N4 (precision).** The occupation regex `is a|is an …$` matches identity and description sentences. All 17 flags on real data (4 dogfood, 13 LoCoMo) are false, e.g. "Cairn is an independent … reimplementation" vs "Cairn is a local-first memory compiler", or "Melanie is a parent" vs "Melanie is a mom".

  The location value keeps trailing words, so "lives in Lisbon" vs "lives in Lisbon with her husband" is flagged although the city is the same. The flags are advisory, so nothing is lost, but combined with N3 a false flag can still hide a fact from the brief.
- **N5 (policy drift).** On equal timestamps the code supersedes by capture id, but P6 says to flag. `ingest` has no way to set `captured_at`, and a missing stamp silently becomes "now" (see item 2).
- **Unchanged from review 1.** The P11 `max_mutation_rate` halt and the `/health` back-off are still unimplemented (no match in `src/**/*.py`). Nothing schedules a "nightly" run. `consolidate` is a manual command.

## README "nightly evolution" verdict

README line 6–7 says: "A compile pass merges duplicates, supersedes stale facts, and flags contradictions without destroying history". Line 42 adds `consolidate` as the "nightly pass".

**More supported than at b935d9d, but still partially supported.**

- **Supported now:**
  - A model-free consolidation command exists and is idempotent on every brain I tried: synthetic, dogfood, conv-26 and conv-30, with the second pass all zeros.
  - History is never deleted.
  - Exact and spelling-variant duplicates merge.
  - Categorical and same-wording numeric changes supersede in true time order for ISO stamps.
  - On a new DB, `compile` no longer re-extracts.
- **Still unsupported:**
  1. "Supersedes stale facts" fails when the stamps are not ISO. That includes the project's own LoCoMo DBs (N2). It also fails when a value is re-asserted inside one batch (N1).
  2. "Flags contradictions" writes an event that nothing reads. Briefs hide the flagged older fact, and the occupation/location flags are mostly false positives on real data (N3, N4).
  3. On any brain created before phase 14, the first `compile` re-extracts every capture (item 5).
  4. "Nightly" is a manual command. There is no scheduler, no P11 mutation-rate halt and no `/health` back-off, while P11 in `docs/compile-policies.md` still claims all three.
  5. Equal-timestamp handling contradicts P6 (N5).

Smallest set of fixes that would make the sentence true:
- the migration backfill;
- ISO normalisation of `captured_at`;
- canonical-by-latest-timestamp in dedupe;
- showing both facts (marked) in the brief when a cluster carries a flag;
- removing `is a|is an` from the occupation slot;
- either implementing the P11 halt or deleting it from the policy doc.

## Not verified

- Behaviour with real model extraction. All of this re-review is deterministic. Scenario A from review 1 was not re-run against a live model.
- Export and history CLI output for flagged facts. I only checked that both rows stay `active` and that the event is written.
- Whether the phase-14 change shifts the LoCoMo score. No benchmark was re-run.
