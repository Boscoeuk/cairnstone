# Tes consolidation exercise 1: the nightly pass on an already-compiled brain

Card: t_de0ab521. Author: Tes. Date: 2026-11-06.
Publication note: LAN addresses, host names and the route alias are genericised (`<lan-node>`,
`local-judge`) for the public repo. No figure or verdict changed.
Code under test: HEAD `b935d9d` (`src/cairnstone/compile.py`, `store.py`, `retrieve.py`, `cli.py`).
Nothing in `src/`, `tests/` or `eval/` was changed. This file is the only thing written to the repo.
The harness scripts are outside the repo, in Tes's local scratch directory
(`run.py`, `run_c.py`, `run_d.py`, `result-a.json`, `result-b.json`).

## Endpoint that answered

- `GET http://<lan-node>:8889/v1/models` returned `{"id": "local-judge", "context_length": 262144}`.
  All model calls in scenario A went there, as `CAIRN_BASE_URL=http://<lan-node>:8889/v1` and `CAIRN_MODEL=local-judge`.
  Telemetry for the last batch-1 call: `engine=lanes`, 47.4 tok/s, TTFT 0.82 s, 605 prompt tokens.
- Correction to the card: that endpoint is a different local inference node from the one the card named.
  The card's instruction gave this address, so I used it. No other endpoint was called.
- The Mac Studio fallback (`127.0.0.1:8460`, glm-5.3-flash) was also up, but it was not used.
- Embeddings for briefs came from local `127.0.0.1:1234` (nomic). No cloud calls were made.
- Run times: batch 1 compile took 4 captures, batch 2 took 5, and the CLI re-compile took 9 captures in 15.2 s.
  The whole of scenario A took 36 s wall-clock.

Concurrency note: while this ran, another worker changed `README.md`, `cli.py`, `mcp_server.py` and
`tests/test_cli.py` in the working tree (uncommitted; it adds a `CAIRNSTONE_*` env prefix that still honours `CAIRN_*`).
None of those edits touch dedupe, supersede or compile logic. They are not mine.

## Scenarios

**A (real model, library path, then the shipped CLI).** The temp DB has one brain.
- Batch 1, dated 2023-05-01, is four captures from Caroline: lives in Berlin; single; nurse for 4 years; favourite hobby is painting landscapes.
- I ran `compile_all(batch1)`.
- Batch 2, dated 2023-06-01, is five captures: moved to Lisbon; a paraphrased duplicate of the hobby; got married; nurse for 5 years; learning guitar (a control on a different slot).
- I ran `compile_all(batch2)`, then two pure re-runs of `dedupe()` + `supersede_contradictions()` with no new captures. A re-run with no new captures is the "nightly" pass.
- Then, on a copy of that DB, I ran the shipped `python -m cairnstone.cli compile --db …`.

**B, C and D (deterministic, no model).** I wrote facts directly with `store.add_fact` and ran only the two consolidation
functions. This isolates the logic from extraction wording.

Snapshot query, used for every state below:
```sql
SELECT f.id, p.path, f.text, f.capture_id, f.status, f.superseded_by, f.duplicate_of
FROM facts f JOIN pages p ON p.id=f.page_id ORDER BY f.id;
SELECT id, kind, subject_id, payload_json FROM change_events ORDER BY id;
SELECT id, page_id, supersedes_version_id FROM page_versions ORDER BY id;
```

### State after batch 2 (scenario A, real model output)
```
f1  c1 active     sup_by=None dup_of=None  Caroline lives in Berlin.
f2  c2 superseded sup_by=9    dup_of=None  Caroline is single.
f3  c3 active     sup_by=None dup_of=None  Caroline has been working as a nurse for 4 years.
f4  c4 active     sup_by=None dup_of=None  Caroline's favourite hobby is painting landscapes.
f5  c5 active     sup_by=None dup_of=None  Caroline moved to Lisbon on 2023-05-25.
f6  c5 active     sup_by=None dup_of=None  Caroline lives in Lisbon.
f7  c6 active     sup_by=None dup_of=None  Caroline's favorite hobby is painting landscapes.
f8  c7 active     sup_by=None dup_of=None  Caroline got married on 2023-05-27.
f9  c7 active     sup_by=None dup_of=None  Caroline is married.
f10 c8 active     sup_by=None dup_of=None  Caroline has been a nurse for 5 years.
f11 c8 active     sup_by=None dup_of=None  Caroline is a nurse.
f12 c9 active     sup_by=None dup_of=None  Caroline started learning the guitar in June 2023.
events: (11, 'fact.superseded', 2, '{"superseded_by": 9}')     page_versions: 1
batch2 summary: accepted=8 rejected=0 duplicates_linked=0 superseded=1
```
Nightly re-run #1 printed `linked=0 superseded=0`, and re-run #2 also printed `linked=0 superseded=0`. Diffing S2 against S3 and S3 against S4 showed
no changes in facts, events, versions or pages.

## Per-check results

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Categorical change (single → married) across batches is superseded | **PASS** (simple case) | f2 `superseded`, `superseded_by=9` ("Caroline is married"). |
| 2 | Old fact kept, not deleted | **PASS** | f2 is still present, with its text, capture and quote. |
| 3 | `superseded_by` points from old to new | **PASS** | f2 → f9. In the D4 case it points the wrong way; see defect D4. |
| 4 | Change event recorded | **PASS** | `change_events` id 11: `fact.superseded`, subject 2, `{"superseded_by": 9}`. |
| 5 | Location change (Berlin → Lisbon) superseded | **FAIL** | f1 "lives in Berlin" and f6 "lives in Lisbon" are both `active` after every pass. Deterministic B2 (identical wording apart from the city) gives `linked/superseded = (0, 0)`. |
| 6 | Numeric change (4 years → 5 years) superseded | **FAIL with real extraction**; PASS only on identical wording | Real model: f3 "has been **working as** a nurse for 4 years" and f10 "has been a nurse for 5 years" are both `active`, because the slot keys differ. Deterministic B3 with identical wording does supersede, but the wrong way round (defect D3). |
| 7 | Different slots on the same page NOT superseded | **PASS** | B4: "has 2 cats" and "has 3 dogs" give `(0, 0)`. A: the guitar, hobby and nurse facts are untouched by each other. |
| 8 | Near-duplicate collapse | **FAIL** | f4 "favour**ite** hobby…" and f7 "favor**ite** hobby…" are not linked (`duplicates_linked=0`), because the key is exact text. |
| 9 | Briefs exclude superseded facts | **PASS** for status; **FAIL** for the result | f2 never appears in non-history briefs. It does appear for "Where did Caroline used to live?" (history mode, by design). But the brief for "Where does Caroline live?" contains f1 Berlin and f5 "moved to Lisbon", **not f6 "lives in Lisbon"**. The `select_facts` Jaccard ≥ 0.5 near-duplicate collapse clusters Berlin with Lisbon and keeps the older fact. |
| 10 | Export excludes superseded facts | **PASS** | `people/caroline.md` does not contain "is single". It does still list both "lives in Berlin" and "lives in Lisbon", and both nurse durations (follows from 5, 6 and 8). |
| 11 | History shows the superseded fact | **PASS** | f2 keeps status, `superseded_by` and its change event. `cairnstone history` reads the same columns and `change_events WHERE subject_id=?`. One caveat: `cmd_history` filters events by `subject_id` alone, so capture and page events with the same numeric id are mixed in. |
| 12 | Nightly re-run (library `dedupe` + `supersede`) is a no-op | **PASS here, but not in general** | A: re-runs #1 and #2 changed nothing. B1 shows a case where the second pass is **not** a no-op (defect D1). |
| 13 | Nightly re-run via the shipped CLI (`cairnstone compile`) is a no-op | **FAIL** | `ok: compiled captures=9 accepted=12 rejected=0 duplicates_linked=11 superseded=2`. Every capture is re-extracted: facts go from 12 to 24 rows, and two new supersede events (12, 13) are written. See D2 and D4. |
| 14 | Page versions | **N/A / note** | The compile never creates a page version (`page_versions: 1` throughout, empty body). Facts all hang off version 1. "Page version history" does not record fact evolution. |

## Defects found

**D1. Supersede considers duplicate rows, so a stale canonical fact survives a pass.** Deterministic, scenario B1.
f1 "Caroline is single" (c1) is the canonical fact. f2 "Caroline is single" (c2) has `duplicate_of=1`. Then f3 "Caroline is married" (c3) arrives.
- Pass 2 printed `(0, 1)`: only f2 was superseded. f1 stayed **active** with `superseded_by=None`. `supersede_contradictions` selects
  active rows without `duplicate_of IS NULL`, so the duplicate f2 replaces f1 in `seen` and f1 is never compared with f3.
- Pass 3 printed `(0, 1)` and superseded f1 → f3.
- So a single pass leaves the brain contradictory ("single" and "married" both canonical-active), and the nightly
  pass is not idempotent: the second run mutates.

**D2. `cairnstone compile` re-extracts every capture on every run.** `cmd_compile` selects all captures
(`SELECT id FROM captures WHERE brain_id = ? ORDER BY id`). Nothing records which captures were already compiled.
- Each nightly run duplicates every fact row: 12 → 24 in scenario A.
- It spends a model call per historical capture.
- It relies on exact-text dedupe to hide the copies.
- f14, a re-extracted "Caroline is single", was not linked as a duplicate because its canonical f2 is superseded. Instead it was
  superseded again (event 12), so every run will add a new superseded copy plus a new history event.

**D3. "Newer" means a higher capture id, not a later `captured_at`.** Scenario B3:
f6 "nurse for 5 years" (captured 2023-06-01) was ingested before f7 "nurse for 4 years" (captured 2023-05-01).
The result was **f6 `superseded`, `superseded_by=7`**, with the older 4-year fact left active. Any backfill or out-of-order import
inverts supersession. The C1 run shows the same: a backfilled "single" beat two newer "married" facts. Both "married"
facts were superseded and "single" stayed active.

**D4. After the capture-order swap, `supersede_contradictions` records the wrong value.** At `compile.py:536-543`, when
`new.capture_id < old.capture_id` the rows swap, but `seen[key] = (value, new)` stores the *current row's* value against
the *other* row. The next same-capture fact is then judged a contradiction of its own fact.
- Clean repro (run_d): captures c1 "single" (2023-05-01) and c2 "married" (2023-06-01), in chronological id order. Facts: a = f1 "is married" (c2), b = f2 "is single" (c1), c = f3 "is married and happy" (c2).
- Result: f2 → f1 is correct. But **f1 "is married" was then superseded by f3**, with event `{"superseded_by": 3}`, although the two agree.
- In scenario A's CLI re-run it caused real loss. f9 "Caroline is married" was superseded by f21, its own re-extracted
  copy. f21 is `active` but `duplicate_of=9`, and briefs and export exclude duplicates. So the **"Caroline is married"
  claim disappeared from both briefs and export**: the two briefs on relationship status return no `is married` fact,
  and the export lines contain only "got married on 2023-05-27".

**D5. Contradiction detection only covers numbers/dates and a six-word relationship lexicon.** (Design limit.) Location,
occupation and any free-text value (Berlin/Lisbon) are never compared. A numeric slot only matches when the model
words both facts identically ("working as a nurse" vs "a nurse"). With real extraction, two of the three planned
contradictions were missed.

**D6. The retrieval near-duplicate collapse picks the stale side of an undetected contradiction.** (`retrieve.py`
`select_facts`, Jaccard ≥ 0.5 within a page, keeps the best score and then the earliest id.) "lives in Berlin" and "lives in Lisbon"
cluster together, and the brief for "Where does Caroline live?" served Berlin. This amplifies D5.

## Verdict on README "nightly evolution"

The README says: "A compile pass merges duplicates, supersedes stale facts, and flags contradictions without destroying
history". PLAN/P11 say: "Nightly evolution … is idempotent".

**Partially supported at best; as shipped through the CLI, unsupported.**
- Supported: history is never deleted. Supersede marks the fact, links it and logs an event. Superseded facts leave
  briefs and export. An exactly-worded categorical change across batches is caught, and a pure library re-run on that brain was a no-op.
- Not supported:
  - Merging only catches exact keys (favourite/favorite missed).
  - Stale-fact supersession misses location and any rewording of a numeric slot.
  - "Flags contradictions" has no flag state: undetected ones stay silently active, and retrieval may serve the stale one.
  - Idempotency fails twice: D1 needs a second pass to converge, and the CLI `compile` re-extracts everything every run (D2).
  - Ordering follows ingestion rather than time (D3).
  - The swap bug (D4) can supersede a correct fact by its own duplicate and hide it from briefs and export.
- There is no separate nightly/consolidation command. The only "nightly" entry point is `cairnstone compile`, which is the D2 path.

## Not verified

- The P11 `max_mutation_rate` halt and the `/health` back-off are not implemented in `compile.py` or `cli.py` (grep found
  neither), so I could not exercise them.
- Behaviour across multiple pages or entities, retraction, and `stale_after_days` decay was not tested.
- Model variance: scenario A ran once. The extraction wording, and so the D5 misses, may differ between runs or models.
  B, C and D are deterministic.

## Suggested fixes (not applied; for the owner to schedule)

1. Restrict `supersede_contradictions` to `duplicate_of IS NULL`, or resolve duplicates to their canonical row first (D1).
2. Fix the swap so the stored value matches the stored row, e.g. `seen[key] = (new_value, new)` (D4). Add a test with
   fact ids out of capture order.
3. Order by `captures.captured_at`, then capture id (D3).
4. Track compiled captures, e.g. a `compiled_at` column or a capture→run table, so that `compile` only processes new ones. Add a
   separate consolidation-only command for the nightly pass (D2).
5. Add a location/occupation slot lexicon, or an LLM-adjudicated contradiction check, writing a `fact.contradiction_flagged` event
   rather than staying silent (D5). Make the retrieval collapse prefer the newest capture when a cluster's members differ in value (D6).
