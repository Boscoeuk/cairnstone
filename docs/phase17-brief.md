# Phase 17 brief — consolidation knowledge-update test

Written by Polly, 2026-11-10 (rev 4, after Tes review round 3 at `b08e3a5`; rev 3 followed round 2 at
`a068e4b`, rev 2 round 1 at `fdfb816`). Tes reviews this
**before any run** and re-checks the result before it is called accepted. No measurement run has
been made: the only executions of this code path are one 1-question smoke (`71315a70`) and a stray
20-question run stopped at question 1 before any answer was judged. Neither is a result; both are
excluded from the question set and quarantined (§P8.9).

**Revision 4 (this version) — round-3 change, one item, no design change:** the date-only column in
`eval/longmemeval/p17_recall_check.py` was broken. `DAY_FMT = "%Y/%m/%d"` was passed the full haystack
string `2023/04/23 (Sun) 08:57`, so `strptime` raised `unconverted data remains`, `parse()` returned
`None` for **every** session, and the "date-only" rule silently degenerated to score order — i.e. (c)'s
top 3, which is why rev 3's table read 68 at every k. The script now parses the date prefix
(`str(date)[:10]`) and **asserts** that every haystack date parses under both rules (3,513 of 3,513
today), so an all-`None` regression fails loudly instead of producing a plausible table. Consequences
corrected in this revision: the differing-keep-set figure at k=4 is **6 of 74, not 59** (§B2, this note,
appendix), the date-only column is 67/63/60/57/48 for k=4/5/6/8/10, and the "why it differs from rev 2"
paragraph now says the difference was this bug, not an unstated tie-break. The pre-registered
full-timestamp rule, k=4, the arms, the ids, the criterion and the gates are unchanged.

Two parts, in this order:

- **Part A — pre-work.** Close `reports/tes-review-4.md` F1–F4, rebuild the harness so that arm (a)
  cannot be contaminated, and re-establish the citation invariant at the frozen code. The KU test
  exercises the contradiction path directly, so it cannot run on code whose contradiction scope is
  undocumented and untested.
- **Part B — the experiment.** Does one nightly consolidation pass make compiled memory more
  correct on knowledge-update questions?

Decisions recorded here are Polly's and are final for this phase; implementation must not
re-litigate them. The defects and the measurements behind them are Tes's, in `reports/tes-review-4.md`
(committed at `68280b9`; do not edit that file).

**Revision 3 (this version) — round-2 changes, all three requested:**

1. **The stray pre-freeze run is stopped.** `ku_paired.py --questions 20 --seed 20261106`, pid 45392,
   started 16:22 from Polly's interactive session on the unfrozen harness, was killed with SIGTERM at
   16:29 before any answer or verdict was written. It held `:8460` (gate §B8.1) and overlapped 19 of
   the 74 eligible ids and 7 of the 20 pilot ids. No `ku-paired-20q.json` was produced. Its partial
   brain and every other pre-freeze artifact are quarantined, with sha256s, in
   `eval/results/ku-quarantine-20261110-pre-freeze/MANIFEST.md` (§P8.9). **No question has been
   judged or read on unfrozen code, so the 74 stays 74.**
2. **Provenance sidecar, fail-closed (§P8.8, §P8.9).** A brain is reused only if `<qid>.meta.json`
   records the frozen code SHA and the config sha256 and both match; missing, malformed or mismatched
   → refuse and recompile. Pre-freeze brains and the pre-freeze smoke JSON are moved (not deleted) to
   the quarantine directory. Tests for the missing/mismatched sidecar are specified.
3. **(d)'s date granularity is pinned (§B2).** Full timestamp, `%Y/%m/%d (%a) %H:%M`, newest first,
   tie-break score descending then session index; unparseable last. The recall table is regenerated
   under that rule by committed `eval/longmemeval/p17_recall_check.py` and pasted with its output.
   26 of the 74 questions have a same-day tie inside the relevance top 4, and at k=4 the full-timestamp
   and date-only rules keep a **different** set on **6 of 74** questions — so the parse rule is part
   of the pre-registration, not a detail.

**Revision 2 — round-1 changes (retained):** arm (d) redefined as
relevance-then-recency with k pre-registered and the recall table included (§B2); harness rewritten
to keep the compiled brain pristine and consolidate a backup copy (§P8); LoCoMo pairing pinned to the
`fe71ff1` brains and the 11-07 baseline JSON, with `.venv/bin/python` and an explicit `--db-dir`
(§B9); citation audit re-scoped: dogfood DB is a continuity check only, a frozen-SHA brain is audited
before question 1, and every KU brain is audited before and after consolidation (§P5); embeddings
endpoint frozen and gated (§P10, §B8); the literal 74 and 20 ids and the exact sampling procedure
written into the brief and the config (§P11, §B3); cross-page collision dry-run added to the
mechanism diagnostic (§P9, §B7); judge `/health` label recorded per question (§P8.6, §B8); `ebe5f6`
corrected to `ebee5f6` and the 1,540-row evidence path named (§C3).

---

# Part A — pre-work (all of it before the run starts)

## P1 — F1: contradiction scope

`_supersede_contradictions` built one `claims` dict across the whole brain. At `fe71ff1` 20 of 43 new
supersessions/flags paired facts on **different pages**, and several are plainly wrong
(`projects/alpha` "first CI run failed" superseded by a `projects/beta` fact; phase-1 vs phase-2
acceptance; conv-26 vs conv-30 counts).

**Decision:** the scan resets its comparison state **per page**, as policy P6 and the phase-16 brief
already specify. Do not invent an entity-key scheme in this phase.

**Known limitation, documented, not fixed here:** some genuinely correct pairs cross pages — user
facts split between `misc/user` and `people/user`, and the Fitbit tenure supersession. They stay
unresolved. Record them with evidence in `docs/compile-policies.md` under P6 and in
`reports/phase17-report.md`. A future phase may key on entity rather than page; out of scope here.

Required test: a fact on page A must be unable to supersede or flag a fact on page B, with the
counter-case (same page, genuinely contradicting) still superseding.

**Consequence for Part B that must be stated in the report:** if the KU arm shows no gain, page scope
is one candidate cause — a LongMemEval update that lands on a different page from the stale claim
cannot be resolved. The §B7 diagnostics exist to tell those cases apart.

## P2 — F2: the N6 test must actually protect the fix

The current `test_phase15` n6 assertion passes even if `_fact_slots` returns `[]` for any
"got married" text. A guard that cannot fail is not a guard.

**Decision:** assert the slot explicitly —
`("cat:relationship_status:caroline", "married") in _fact_slots("Caroline got married in May 2023")`
— and assert the stale "single" fact is superseded **by the married fact**
(`status == "superseded"` and `superseded_by` equal to the married fact's id), not merely inactive.
Then prove the guard by running a mutant `_fact_slots` returning `[]` and confirming the test fails.

## P3 — F3: identifiers are part of the key, "as of" suffixes are not a value

Canonicalisation strips punctuation that used to keep keys apart, so "Phase 1"/"Phase 2", "budget
600/1200/4000" and "conv-26/conv-30" collapse into one slot with the number as the value; and about 12
paraphrase pairs differ only by an "as of <date>" suffix. Around 25 of the 40 new flags are false
because of these two effects.

**Decision:**

(a) A bare trailing "as of <date>" clause must not count as a differing value when comparing values.
(b) Digits that are part of a **name** — `phase N`, `conv-NN`, `bNNN`, or a leading label token —
belong to the slot key, not to the value.

Required tests: phase 1 vs phase 2 stay active (no supersede, no flag); budget 600 vs 1200 stay
active; an "as of 2023-05-22" paraphrase does not flag.

## P4 — F4: state-verb immunity (last; must not delay the freeze indefinitely)

"X married Y" is not recognised as a state, so a later state can never retire it; meanwhile false
event hits (`met`, `left`, `joined`) make state sentences permanent.

**Decision:** add `married`, `wed`, `eloped`, `separated`, `engaged`, `relocated` to the state
phrasings. For `met`/`left`/`joined`, anchor them to the verb position after the subject, or drop
them from the immunity rule — implement whichever can be tested, and say which you chose.

F4 is on the KU critical path, so it lands with P1–P3 if it can be tested cleanly. If it cannot, the
run proceeds without it and the report names F4 as an unclosed limitation — it is not a reason to
delay the overnight window by more than one pass.

## P5 — citation integrity at the frozen code (re-scoped as requested)

The `1,640 / 1,640` figure in the README and `reports/tes-review-4.md` was measured on the
**2026-11-07** `eval/dogfood/session.db`, by older extraction code. It is a **continuity check only**:
it cannot prove anything about facts produced by today's HEAD. It must be labelled that way wherever
it appears.

Write `eval/quote_integrity_audit.py` (new; deterministic, read-only, no model calls, no embedding
calls) that, for each database passed on the command line, verifies for **every** fact row:

```
facts.quote == captures.content[facts.span_start:facts.span_end].strip()
```

**Precision matters here, verified at `68280b9`:** `store.add_fact` writes
`quote = content[span_start:span_end].strip()` (`src/cairnstone/store.py:450`) and bounds-checks the
span as Python `str` indices (`0 <= span_start < span_end <= len(content)`, line 447). So the
invariant to assert is the **stripped** slice on `str` offsets — not byte-equality, and not
`bytes` offsets. The audit must report, separately: (i) mismatches of the stripped slice; (ii) rows
whose unstripped slice differs only by leading/trailing whitespace (expected, informational);
(iii) facts with a missing capture or an out-of-range/empty span.

Report per database: facts checked, each of those counts (with fact id, capture id, span), and the
sha256 of the database file.

Run it at the frozen SHA, in this order, and report each result with database identity, file hash and
timestamp:

1. **Pre-run gate (blocking):** compile **one** brain at the frozen SHA — use the excluded
   `71315a70` (≈28 min at the measured rate, §B4) — and audit it. This is the only audit that tests
   code-produced facts at the frozen SHA, so it must pass with **zero** mismatches before question 1.
2. **Every KU brain, twice:** once as compiled (pristine `<qid>.db`, before consolidation) and once
   after the consolidation pass (`<qid>.consolidated.db`). Zero mismatches in both, or the run stops.
3. **Continuity only:** `eval/dogfood/session.db` (the 1,640 figure), `eval/results/lme-db/*.db`, and
   the pinned `fe71ff1` LoCoMo brains (§B9). Same database, new auditor — it must still read 1,640 /
   1,640 on the dogfood DB, but label the row "continuity check, facts extracted by pre-freeze code".

A single mismatch in (1) or (2) blocks acceptance. Add a test that mutates one `facts.quote` in a
scratch copy and asserts the audit fails (it must be able to fail), and a second test that mutates a
`span_end` and asserts the out-of-range/mismatch path fires.

## P6 — suite state

The suite is **133 passed at `fe71ff1`** (phase 16, accepted — `reports/tes-review-4.md`, reproduced
by Tes). `115 passed` is the count at `d73b6ae` and belongs only to pre-fix trees; do not attach it to
`fe71ff1`. The pre-work commit must report its own measured pass count
(`.venv/bin/python -m pytest -q` from the repository root; bare `python3` is Xcode 3.9 and fails
collection).

## P7 — collateral probe (evidence that F1+F3 did what they claim)

Re-run Tes's collateral probe on the same corpus (27 real databases, ~10.5k active facts:
`eval/dogfood/session.db`, the conv-26 and conv-30 DBs, and the 22 LongMemEval result DBs) on
**SQLite backup copies**, two passes, and report superseded / flagged / duplicate-linked counts
against her baselines: `fe71ff1` = 3 / 40 / 57; `d73b6ae` = 0 / 9 / 33. The point is that the false
flags fall while the three correct supersessions survive — or are lost only under the documented
cross-page limitation. The phase-15 P11 guard (`max_mutation_rate`) must still halt a runaway pass.

## P8 — harness rewrite (prerequisite; arm (a) must be provably unconsolidated)

Current `eval/longmemeval/ku_paired.py` cannot support this experiment as it stands, verified by
reading it at `fdfb816`:

- `run_one` calls `compile_question(question, db_path, client, True)` — `recompile=True`, so the
  brain is rebuilt from scratch every run and the cache is ignored;
- it then calls `cairn_compile.consolidate(conn, brain_id)` on `<qid>.db` **in place**, so a reused DB
  is already consolidated and arm (a) would be read from a mutated brain;
- `consolidate(conn, brain_id, max_mutation_rate=None)` — the harness never passes the rate, so the
  P11 guard is silently off, unlike the CLI (`--max-mutation-rate` default `0.2`);
- there are only two arms (before/after); (c) and (d) do not exist;
- `select_knowledge_update` samples the **full KU pool**, not the eligible 74, and the seed is in the
  harness rather than in a committed config.

**Required changes, frozen with the pre-work commit:**

1. **Pristine brain.** Compile once into `eval/results/ku-db/<qid>.db`. Reuse is **conditional on the
   provenance sidecar in item 8** — never "reuse as-is". After compiling (or reusing), record `sha256`
   of the DB file and store it in the result row.
2. **Consolidate a copy, never the original.** Make a SQLite backup copy with the `sqlite3` backup API
   to `eval/results/ku-db/<qid>.consolidated.db`, run `consolidate(conn, brain_id,
   max_mutation_rate=0.2)` **on the copy**, and record its sha256 too. Arm (a) answers from
   `<qid>.db`; arm (b) answers from `<qid>.consolidated.db`.
3. **Assert non-contamination.** Before answering arm (a), re-read the pristine DB's sha256 and assert
   it equals the value recorded at compile time. After the whole question completes, assert it again.
   A mismatch aborts the run.
4. **Four arms in one pass per question:** (a) pristine brief, (b) consolidated-copy brief, (c) and (d)
   from the dataset only (no brain, no embeddings). (c) reuses `lme_eval.keyword_backend` unchanged;
   (d) is the new function defined in §B2.
5. **Config-driven selection.** The harness takes `--ids-file` (the committed config, §B5) and runs the
   literal ids it lists, in the listed order. No `random` call inside the harness.
6. **Judge identity per question.** Immediately before judging each question, GET the judge's
   `/health` and record `name`, `label`, `upstream_model` and the UTC timestamp in the row. If the
   label changes from the value recorded at run start, stop the run (§B11).
7. **Tests** in `tests/test_phase17.py` (no model calls; a stub client):
   - a contradiction injected into a scratch brain: arm (a)'s brief must still contain the stale fact
     as active, arm (b)'s must show it superseded — i.e. (a) is read from the unconsolidated DB;
   - the pristine sha256 is unchanged after a full `run_one`;
   - a second `run_one` on an existing DB does not recompile (capture/fact counts and sha identical,
     stub client asserts zero extraction calls) **when the sidecar matches**;
   - a DB with a **missing** sidecar is refused: the harness recompiles rather than reading it, and the
     row records `reused=false` with reason `sidecar-missing`;
   - a DB with a sidecar whose `code_sha` or `config_sha256` differs from the frozen values is refused
     the same way (`sidecar-mismatch`), and the stale DB is never read by any arm;
   - the consolidation call receives `max_mutation_rate=0.2` (assert via monkeypatched
     `cairn_compile.consolidate`).
8. **Provenance sidecar (fail-closed).** At compile time write `eval/results/ku-db/<qid>.meta.json`
   containing: `question_id`, `code_sha` (the frozen commit SHA the run is pinned to), `config_sha256`
   (sha256 of the committed config file, §B5), `dataset_sha256`, `compile_started_utc`,
   `compile_finished_utc`, `captures`, `facts`, and `db_sha256` (sha256 of the finished DB file).
   Reuse rule, implemented as one function and unit-tested: read the sidecar; if it is missing, or
   unparseable, or `code_sha != frozen_sha`, or `config_sha256 != config_sha256(frozen config)`, or
   `db_sha256 != sha256(<qid>.db)`, then **do not read the DB** — recompile it and rewrite the sidecar.
   Never repair a sidecar by hand; the harness owns it. The consolidated copy gets the same treatment:
   `<qid>.consolidated.meta.json` recording the pristine sidecar's `db_sha256` it was derived from, the
   `max_mutation_rate` used, the returned consolidation counts, and its own `db_sha256`; a consolidated
   DB whose recorded source hash does not match the current pristine hash is rebuilt, not reused.
   Rationale: without this, a brain compiled by pre-freeze code is silently read as if it were frozen,
   which is exactly the contamination Tes round 2 identified.
9. **Quarantine of everything pre-freeze.** Before the freeze, move (do not delete)
   `eval/results/ku-db/*` and `eval/results/ku-paired-*.json` that were produced before the frozen SHA
   into `eval/results/ku-quarantine-20261110-pre-freeze/`, with a `MANIFEST.md` listing each file's
   sha256, size, provenance and why it cannot be reused. **Done in this revision** — the directory now
   holds `71315a70.db` (the smoke brain, 228 captures / 388 facts, `b6560579…c92c3`), the stray run's
   partial `1cea1afa.tmp` plus its `-shm`/`-wal`, and `ku-paired-smoke.json`. `eval/results/ku-db/` is
   now empty, so every brain there after the freeze is frozen-SHA provenance-checked. A test asserts
   that a brain placed in `ku-db/` without a sidecar is refused (item 7), which is the mechanism that
   keeps a future stray artifact out.

## P9 — cross-page collision dry-run (B7 needs a measure, not a promise)

Add a **read-only** function to `src/cairnstone/compile.py` (for example
`scan_cross_page_collisions(conn)`) that reuses the existing slot and value-comparison helpers to find,
brain-wide and **without mutating anything**, every slot whose facts on different pages would have
been paired by the pre-F1 brain-wide scan. It returns: candidate cross-page pairs (count and ids),
which of them the per-page rule now skips, and — when given the fact ids selected into arm (a)'s
brief — how many of those pairs involve a fact the answerer actually saw.

Test: run it on a scratch brain and assert fact statuses and counts are identical before and after
the scan (proving it is a dry run). Report the count per question in §B7; if it is zero across the
sample, the report must say the page-scope rule was not exercised rather than implying it was.

## P10 — embeddings freeze and gate

`retrieve.build_brief` calls the embedding endpoint (`src/cairnstone/retrieve.py:35`):
`http://127.0.0.1:1234/v1/embeddings`, model `text-embedding-nomic-embed-text-v1.5`, 768d. Arms (a)
and (b) cannot run without it, and a silent endpoint change would be an unfrozen variable.

**Freeze:** record URL, model id and vector dimension in the config (§B5). **Gate (§B8):**
`/v1/models` must list that exact model id, and one test embedding must return 768 floats. Record the
identity in the result file. The no-cloud assertion covers this URL too.

## P11 — pre-registered question selection (no sampling at run time)

The 74 eligible ids and the 20 pilot ids are written into this brief and into the committed config.
They were produced by `eval/longmemeval/p17_ids.py` (committed with this brief; dataset-only, no model
calls):

```
eligible = knowledge-update questions in split "s", minus {08e075c7, 0f05491a, 2133c1b5_abs, 71315a70},
           sorted by question_id ascending
pilot20  = random.Random(20261110).sample(eligible, 20), then sorted by question_id ascending
```

The pilot is a subset of the 74, so extending is not re-sampling. The harness must fail closed if the
config's id list and the dataset's eligible set disagree.

---

# Part B — the experiment

## B1 — the claim under test

Cairnstone's product claim is that a nightly consolidation pass improves a memory over time. The
first test of that claim is knowledge-update: an earlier value is stated, a later session changes it,
and the correct answer is the current value.

**Thesis holds only if arm (b) beats arm (a) AND arm (b) beats arm (d).** Anything else is reported as
"not shown at this n", never as "consolidation does not work".

## B2 — arms

One brain per question, compiled once; every arm uses the same answerer, engine and judge.

| arm | definition |
|---|---|
| (a) | Cairnstone as the compiler left it — `retrieve.build_brief(conn, brain_id, question, budget_tokens=600)` against the **pristine** `<qid>.db`, **no** consolidation call. Note: `compile_all` itself runs dedupe/supersession, so (a) is "post-compile, pre-nightly-pass"; (b)−(a) isolates the nightly pass only. |
| (b) | The same brain after **one** nightly pass: `compile.consolidate(conn, brain_id, max_mutation_rate=0.2)` on `<qid>.consolidated.db` — the function `cairnstone consolidate` calls, with the CLI's default rate (`src/cairnstone/cli.py:364`, `--max-mutation-rate` default `0.2`). Verified 2026-11-10: there is **no installed cron or launchd job** for cairnstone on this machine, so the CLI command is the nightly entry point and (b) is that command's code path. Record the returned counts and any `PolicyHalt`. |
| (c) | Keyword retrieval, as committed in `eval/longmemeval/lme_eval.py::keyword_backend`: top-3 whole sessions by length-normalised lexical overlap, verbatim, each prefixed with its session date. Unchanged code. |
| (d) | Keyword retrieval **relevance first, then recency**, new function `keyword_relevance_recency_backend(question)` in the same module: score every session with the *same* `(c)` score and tokeniser (imported, not reimplemented); take the top **k = 4** by that score; order those 4 by the parsed session date **full timestamp descending** — `datetime.strptime(date, "%Y/%m/%d (%a) %H:%M")`, unparseable last, tie-break score descending, then session index ascending; keep **3**; identical prompt, identical `ANSWER_SUFFIX`, identical session-date prefix. |

**(d) was redefined after Tes round 1**, and its date rule was pinned after round 2. As originally
written — every session with overlap>0, keep the 3 newest — it put an answer session in the top 3 on
only **36/74** questions (against 71/74 for (c)), so beating it would have proved nothing.

**Date granularity is pre-registered as the full timestamp, and it is load-bearing.** The haystack
dates carry times (`2023/04/23 (Sun) 08:57`). 26 of the 74 questions have a same-day tie inside the
relevance top 4, and at k=4 the full-timestamp rule and a date-only rule keep a **different set on 6
of 74** questions. The parse format is therefore frozen in the config (§B5), not left to the
implementation. Recall under the pre-registered rule, computed by committed
`eval/longmemeval/p17_recall_check.py` (dataset-only, no model calls, no brains; run 2026-11-10 after
the rev-4 parse fix):

```
$ PYTHONPATH=src:. .venv/bin/python eval/longmemeval/p17_recall_check.py
dates_total 3513 parsed_full 3513 parsed_day 3513
eligible_n 74
sessions_per_q mean 47.5 min 39 max 55
sessions_with_overlap mean 28.4 min 7
answer_sessions_per_q set [2]
unparsed_full_timestamp 0
questions_with_same_day_tie_in_top4 26
questions_where_full_and_day_k4_keep_differ 6
c_top3_any_answer 71/74 latest 68/74
k  full_any full_latest day_any day_latest
3  71       68          71      68
4  67       67          67      67
5  61       61          63      63
6  60       60          60      60
8  54       54          57      57
10 45       45          48      48
```

| (d) candidate set | **pre-registered: full timestamp** — latest answer session kept | pre-registered: any answer session kept | date-only variant (NOT used) — latest kept |
|---|---|---|---|
| k=3 (same set as (c), reordered) | 68/74 | 71/74 | 68/74 |
| **k=4 (pre-registered)** | **67/74** | **67/74** | 67/74 |
| k=5 | 61/74 | 61/74 | 63/74 |
| k=6 | 60/74 | 60/74 | 60/74 |
| k=8 | 54/74 | 54/74 | 57/74 |
| k=10 | 45/74 | 45/74 | 48/74 |
| (c) top-3 by score, for reference | 68/74 | 71/74 | — |
| (d) as originally written (all overlap>0, newest 3) | 36/74 | — | — |

**Why the date-only column changed from rev 3 — it was a bug in the script, not a tie-break choice.**
Rev 3 printed 68 for every k≥3 because `DAY_FMT = "%Y/%m/%d"` was handed the full timestamp
`"2023/04/23 (Sun) 08:57"`; `strptime` raised `unconverted data remains`, `parse()` returned `None` for
all 3,513 sessions, and the sort fell back to the score order already in `scored`, i.e. (c)'s top 3.
Rev 4 parses the date prefix instead, and the script now asserts that every date parses under both
rules, so this cannot recur silently. Rev 2's date-only numbers (67/63/60/57/47) were therefore
essentially right; the fixed script gives 67/63/60/57/48. The pre-registered rule stays the full
timestamp: it is the format the haystack actually carries, 26 questions have same-day ties in the top
4, and 6 of 74 questions keep a different set at k=4 — a real but smaller effect than rev 3 claimed.

**k = 4 is pre-registered** rather than 3, because at k=3 (d) shares (c)'s candidate set exactly and
differs only in ordering — a contrast too weak to mean anything in the other direction. At k=4 one
relevant session is dropped in favour of recency while retaining 67/74 latest-answer recall under the
frozen rule: a genuine recency-preferring policy, not a strawman. Also measured (same script, same
run): 47.5 sessions per question, 28.4 of them with overlap>0 (minimum 7), 0 unparsed full timestamps,
and exactly 2 answer sessions per question in all 74.

Fairness note to carry into the report: (c) and (d) read raw sessions, which already carry absolute
session dates; Cairnstone briefs carry capture dates too (commit `ebee5f6`). Both sides have date
information, so a Cairnstone win is not a date-format artefact.

Do not change extraction, retrieval ranking, `build_brief` beyond the committed date fix, or the
citation invariant as part of this phase.

## B3 — questions (literal ids; nothing sampled at run time)

Dataset: `eval/datasets/longmemeval_s_cleaned.json`, split `s` (full haystack — not `oracle`; an
oracle haystack would flatter both keyword arms).

Knowledge-update population: **78** questions. **Excluded as previously used in tuning or smoke — 4
ids:** `08e075c7`, `0f05491a`, `2133c1b5_abs` (the three KU questions in the phase-13 20-question run,
`eval/results/longmemeval-s-600-20q-20261107-162311Z.json`, quoted in the README as "1 of 3") and
`71315a70` (the 1-question smoke of 2026-11-10, and the brain used for the §P5 pre-run audit gate).

**Eligible 74, question_id ascending, verbatim from `eval/longmemeval/p17_ids.py`:**

```
01493427 031748ae 031748ae_abs 06db6396 07741c44 07741c45 0977f2af 0ddfec37 0ddfec37_abs
0e4e4c46 10e09553 184da446 18bc8abd 1cea1afa 2133c1b5 22d2cb42 2698e78f 2698e78f_abs
26bdc477 3ba21379 41698283 42ec0761 45dc21b6 4b24c848 4d6b87c8 50635ada 5831f84d
59524333 5a4f22c0 5c40ec5b 603deb26 6071bd76 618f13b2 69fee5aa 6a1eabeb 6a27ffc2
6aeb4375 6aeb4375_abs 72e3ee87 7401057b 7a87bd0c 7e974930 830ce83f 852ce960 89941a93
89941a94 8fb83627 945e3d21 9bbe84a2 9ea5eabc a1eacc2a a2f3aa27 affe2881 b01defab
b6019101 ba61f0b9 c4ea545c c6853660 c7dc5443 cc5ded98 ce6d2d27 cf22b7bf d7c942c3
dad224aa db467c8c dfde3500 e493bb7c e61a7584 e66b632c eace081b ed4ddc30 f685340e
f685340e_abs f9e8c073
```

**Pilot 20, question_id ascending, `random.Random(20261110).sample(eligible, 20)` then sorted:**

```
2698e78f_abs 45dc21b6 4b24c848 50635ada 5a4f22c0 5c40ec5b 6aeb4375_abs 72e3ee87 7a87bd0c
7e974930 89941a93 8fb83627 945e3d21 a2f3aa27 affe2881 ce6d2d27 d7c942c3 e61a7584
f685340e f685340e_abs
```

Execution order: the 20 pilot ids first (in the listed order), then the remaining 54 in question_id
ascending order. Any partial n<74 result is labelled **PARTIAL (n=X of 74)**; only n=74 is the
confirmatory set. A pilot cannot accept the thesis; it can show direction and mechanism.

## B4 — budget and the runtime decision (measure, then decide — no early stopping on results)

Grounding numbers, all measured:

- one extraction call per capture; captures per KU question 209–236 (mean 223 over the 74 eligible
  questions, computed from the dataset with the `lme_eval.session_chunks` 3,000-character rule);
- **measured 2026-11-10 15:50 → 16:14 on `71315a70` (read live while it was still compiling; the
  finished brain is now quarantined as
  `eval/results/ku-quarantine-20261110-pre-freeze/71315a70.db`, 228 captures / 388 facts): max
  `capture_id` in `facts` = 196 of 228 captures in 24.4 minutes — 7.5 s per extraction call**, against
  the 2–4 s the phase-13 build report recorded. Caveat: another agent was using `:8460` at the same
  time, so 7.5 s is pessimistic, not a clean benchmark. Reproduce the count read-only with
  `eval/longmemeval/p17_smoke_progress.py` (committed; point it at the quarantined brain).

At 7.5 s/capture (≈28 min per question):

| scope | compile calls | wall time at 7.5 s/call |
|---|---|---|
| 20 (pilot) | ~4,460 | ≈ 9.3 h |
| 74 (full) | ~16,500 | ≈ 34 h |

**Decision, written before the run:** the full 74 does not fit one overnight window. The overnight run
is the **20-question pilot** (≈9.3 h); the remaining 54 are compiled on following nights from the
cached per-question DBs. Extension to 74 happens **whatever the pilot shows** — there is no
"stop early because it looks good/bad" rule; the only limit is the window. If the measured rate after
the first 3 pilot questions projects more than 20 inside the remaining window, continue in the
pre-registered order and label the result PARTIAL (n=X of 74). Do not silently shrink to whatever
number finished.

Disk: ≈1 MB per brain, ≈75 MB for the full set plus consolidated copies; require ≥2 GB free (285 GB
free at 2026-11-10 16:14).

## B5 — freeze

Write `eval/longmemeval/ku-phase17-config.json` and commit it **before** the first question runs. It
must contain, verbatim:

- the frozen code SHA (the pre-work commit, after P1–P11 are green) and `git status` clean;
- dataset path, split, the literal 74 eligible ids, the literal 20 pilot ids, the execution order,
  and the sampling procedure string (`p17_ids.py`, seed 20261110);
- `budget_tokens = 600`;
- answerer: endpoint URL, model id, engine identity as reported by `/v1/models`, `temperature=0`,
  `max_tokens=120`, and the `ANSWER_SUFFIX` string unchanged;
- judge: endpoint URL, model id, and the `/health` identity (`name`, `label`, `upstream_model`)
  recorded at run start, plus the rule that any per-question change stops the run;
- embeddings: URL `http://127.0.0.1:1234/v1/embeddings`, model `text-embedding-nomic-embed-text-v1.5`,
  dimension 768;
- consolidation parameters (`max_mutation_rate=0.2`);
- arm definitions verbatim from §B2, including **k=4** for (d) and, explicitly, (d)'s date rule:
  `d_date_parse_format = "%Y/%m/%d (%a) %H:%M"`, `d_order = "parsed date descending"`,
  `d_tiebreak = "score descending, then session index ascending"`, `d_unparseable = "last"`,
  `d_k = 4`, `d_keep = 3`;
- provenance: `provenance_sidecar = "<qid>.meta.json"`, `consolidated_sidecar =
  "<qid>.consolidated.meta.json"`, `reuse_rule = "fail closed: missing/mismatched sidecar ⇒ recompile,
  never read"`, and the quarantine directory `eval/results/ku-quarantine-20261110-pre-freeze/` as the
  only place pre-freeze artifacts live;
- the success criterion text from §B6, the McNemar thresholds, and the MDE table;
- the runtime decision rule from §B4.

The result JSON must record a sha256 of that config plus every one of those fields, so the freeze is
inspectable afterwards. **One answerer, one judge, one engine for all four arms.** No mid-run
substitution: if an endpoint changes identity mid-run, stop and restart rather than mix identities.

## B6 — pre-registered success criterion

Primary (both required, exact two-sided McNemar on paired per-question outcomes):

1. (b) vs (a): `p < 0.05` with discordant pairs in the direction "a wrong → b right" outnumbering
   "a right → b wrong";
2. (b) vs (d): `p < 0.05` in the same direction.

Running both as an AND gate (intersection-union) needs no multiplicity correction. (c) is descriptive,
not gating. **The confirmatory test is run only at n=74**; at n<74 the same numbers are reported as
descriptive with the label PARTIAL.

Report, for every pair among {a,b,c,d}: both-correct, both-wrong, and the two discordant counts, with
the exact p value.

Minimum detectable effect (exact McNemar, two-sided α = 0.05; arithmetic verified by Tes round 1):

| n | discordant pairs D | reaches p<0.05 | does not |
|---|---|---|---|
| 74 | 10 | 9:1 (p=.021) | 8:2 (.109) |
| 74 | 15 | 12:3 (.035) | 11:4 (.118) |
| 74 | 20 | 15:5 (.041) | 14:6 (.115) |
| 20 (pilot) | 6 | 6:0 (.031) | 5:1 (.219) |
| 20 (pilot) | 8 | 8:0 (.008) | 7:1 (.070) |
| 20 (pilot) | 10 | 9:1 (.021) | 8:2 (.109) |
| 20 (pilot) | 12 | 10:2 (.039) | 9:3 (.146) |

So at n=74 this test can confirm only a **large** effect (roughly a 4:1 gain-to-loss ratio among
discordant pairs); at n=20 only a near-total win. State this next to the result, not in a footnote.
Report Wilson 95% intervals per arm — at n=74 a point estimate near 50% carries ±11 points.

## B7 — mechanism diagnostic (required; without it a null result is uninterpretable)

Per question, record:

- consolidation counts (`duplicates_linked`, `superseded`, `flagged`) and any `PolicyHalt`;
- whether ≥1 superseded fact was **in the pre-consolidation brief** (the stale claim the answerer
  actually saw) — this is the mechanism firing;
- whether the superseding fact was selected into the post-consolidation brief;
- the §P9 dry-run cross-page collision count: candidate cross-page pairs the per-page rule skipped,
  and how many involve a fact selected into arm (a)'s brief;
- `active_before` / `active_after` fact counts, `brief_tokens` per Cairnstone arm,
  `gold_support_in_brief` per Cairnstone arm, judge verdict + `judge_ambiguous` + `finish_reason`,
  the judge `/health` label used, and all four answers verbatim.

If **no** question had a stale fact in its brief superseded, the report must say "mechanism not
exercised on this sample", not "no effect". If the cross-page count is >0 and the affected questions
are the ones where (b) failed, say so — that is the P1 limitation showing up in the data.

## B8 — gates (all checked immediately before the first question; log each result)

1. **:8460 idle.** `/v1/models` answers and reports `glm-5.3-flash`; a 1-token completion returns;
   `pgrep -f "eval/(harness|lme_eval|ku_paired)"` is empty. **State at 2026-11-10 16:29:** the
   `71315a70` smoke finished (228/228 captures, 388 facts) and its brain is quarantined; the stray
   `ku_paired` run (pid 45392) was killed and no `ku_paired` process remains. Re-check before question
   1 — do not assume.
2. **Embeddings up.** `http://127.0.0.1:1234/v1/models` lists
   `text-embedding-nomic-embed-text-v1.5` and a test embed returns 768 floats (verified up
   2026-11-10 16:13 and again at 16:29).
3. **Judge healthy.** The judge endpoint answers `/v1/models`; a 3-call sanity probe in which the gold
   answer is submitted as the answer returns CORRECT 3/3. Record the `/health` identity verbatim.
   **Verified 2026-11-10: `http://127.0.0.1:8000/v1` (documented default) is DOWN.** The pinned route
   is `CAIRN_JUDGE_URL=http://spark-side:8889/v1`, `CAIRN_JUDGE_MODEL=spark-side-model`, whose
   `/health` label at 16:29 was "DeepSeek-V4.1-Flash-1017 EXL3 EAQ v1 2.9bpw + drowzeys Keys overlay
   (spark-side flag, Mia recipe c7f2b85, image exl3-tp2-8a98ae503d85) + 2200 MHz cap". Whatever is used must be
   recorded and identical for all arms, for every question, and for §B9.
4. **No cloud.** Every endpoint URL is loopback or `the LAN address`; assert it in the harness and record
   the URLs (answerer, judge, embeddings) in the result file.
5. **Frozen state.** `git status` clean at the frozen SHA; config committed and its sha256 recorded.
6. **Citation audit gate.** §P5 item 1 passed with zero mismatches.
7. **No recompile** of the LoCoMo per-sample DBs (§B9).
8. **No pre-freeze brain can be read.** `eval/results/ku-db/` contains only `<qid>.db` files with a
   matching `<qid>.meta.json` whose `code_sha` equals the frozen SHA and whose `db_sha256` equals the
   file's current hash; any other file is moved into the quarantine directory (moved, not deleted)
   before question 1, and the harness would refuse it anyway (§P8.8). Confirm the quarantine manifest
   still lists every pre-freeze artifact with its sha256.

## B9 — post-run: the LoCoMo date-format re-measure (separate result, separate claim)

The committed date fix (capture dates in records + the `### Time` resolution rule, `ebee5f6`) changes
answer format. Re-measure LoCoMo **after** the KU run, at the same frozen SHA, same answerer and
judge.

**Pairing must not be confounded by compile churn** (already 12 lost and 10 gained between builds).
Pin the `fe71ff1` brains and the baseline JSON, verified present 2026-11-10:

- brains: `eval/results/cairnstone-db/conv-26.db`,
  `conv-30.db` (mtime 2026-11-07);
- baseline: `eval/results/2026-11-07-cairnstone-b600-ps75-s2-q150-195905Z.json`.

Copy both into the repo (`eval/results/cairnstone-db-fe71ff1/` and
`eval/results/locomo-baseline-fe71ff1-195905Z.json`), record sha256 of the copies **and** of the
sources, and assert source == copy. Then run:

```
CAIRN_JUDGE_URL=<pinned> CAIRN_JUDGE_MODEL=<pinned> PYTHONPATH=src:. .venv/bin/python -m eval.harness \
  --backend cairnstone --limit 2 --questions-per-sample 75 --max-questions 150 \
  --brief-budget 600 --judge-model <pinned> --db-dir eval/results/cairnstone-db-fe71ff1
```

`.venv/bin/python`, not `python3`. No `--recompile` (the pinned brains already exist). `--db-dir` does
not exist in `eval/harness.py` today (`CairnBackend.__init__` takes `db_dir` but the CLI never passes
it, verified at `fdfb816`), so exposing it is a small pre-work change that must land in the frozen
commit; if it is not added, the alternative is to copy the pinned brains into
`eval/results/cairnstone-db/` after recording the sha256 of the 11-06 files being replaced — say which
was done.

Pair question-by-question against the pinned 11-07 baseline JSON (same 150 questions, seed and
selection) and report: overall accuracy, temporal accuracy, outside-temporal accuracy, discordant
pairs and McNemar p, mean context tokens, and the sha256s of both brain files.

Report it as **a formatting fix, not a retrieval gain**: the mechanism is that relative-date answers
now resolve to absolute dates, and the pre-registered expectation is a temporal-category gain with no
change outside temporal questions. If outside-temporal accuracy moves, say so — that would mean the
change is doing something else.

## B10 — report requirements

`reports/phase17-report.md` plus the artifacts, with every number measured, not asserted:

- n (and PARTIAL/PILOT label if n<74), frozen SHA, `git status` clean, config sha256, the literal id
  list actually run;
- answerer: endpoint, model, engine identity, temperature, max_tokens;
- judge: endpoint, model, `/health` identity and label, blind-by-construction statement (the judge
  prompt carries question, gold and predicted answer only — `harness.judge`, verified: no arm label
  can reach it; arms are judged independently, never side by side), sanity probe result;
- artifact paths: `eval/longmemeval/ku-phase17-config.json`,
  `eval/results/ku-paired-b600-q<n>-<UTC stamp>.json`, per-question brains under
  `eval/results/ku-db/` (pristine and consolidated, with sha256s) **and their provenance sidecars**
  (`<qid>.meta.json`, `<qid>.consolidated.meta.json`), the quarantine manifest
  `eval/results/ku-quarantine-20261110-pre-freeze/MANIFEST.md`, the quote-integrity audit output,
  the cross-page collision counts, the LoCoMo result file and pinned brain sha256s;
- per-arm table: accuracy, Wilson 95% CI, mean/median prompt tokens, latency, judge-ambiguous count;
- all six pairwise discordant tables with exact McNemar p, and the explicit statement that the
  confirmatory test was run only at n=74;
- the §B7 mechanism diagnostic, including questions where consolidation fired and where it did not;
- the §P5 integrity counts (with the dogfood row labelled continuity-only) and the §P7 collateral
  counts;
- the runtime decision actually taken and why;
- **what was not verified.**

## B11 — stop conditions

- Judge endpoint down or `/health` identity changed mid-run → stop; do not substitute.
- `:8460` or `:1234` busy with another eval → wait; do not interleave (prefix-cache and latency
  measurements become meaningless).
- `PolicyHalt` on a brain → record it, treat that question's "after" as unchanged, and continue; do
  not raise the rate to force a mutation.
- Any non-local endpoint → stop.
- P1–P3 not closed and green, or the §P5 pre-run audit non-zero → do not start the run.
- Pristine DB sha256 changed after a question → stop; arm (a) is contaminated.
- Any arm reads a DB whose sidecar does not match the frozen SHA/config sha256/DB hash → stop. (The
  harness refuses and recompiles by design; if a row still reports `reused=true` with a mismatch, that
  is a bug, not a warning.)
- A new process starts holding `:8460` mid-run (another eval launched by anyone) → stop and restart the
  question; do not interleave.

---

# Part C — wording corrections that must land with this phase

1. **Test count.** 133 at `fe71ff1`; 115 at `d73b6ae`. Do not attach 115 to `fe71ff1`.
2. **Phase numbering.** Phase 16 = `fe71ff1` (accepted, `reports/tes-review-4.md`). This phase is 17.
   The date-fix comments in `src/cairnstone/retrieve.py` and the `ku_paired.py` docstring say
   "Phase 16" — relabel them phase 17. Comment-only change; no behaviour change.
3. **README accuracy row.** If an accuracy row is kept, it uses the **1,540-question LoCoMo run:
   73.2%, Wilson 95% 70.9–75.3** — not the 150-question 78%. The evidence exists and is verified
   2026-11-10 at
   `~/the measurement worktree/evidence/model-evals/cairnstone-phase12-review-20261106/`:
   `REVIEW.md`, `rejudge-same-judge.jsonl` = **1,540 rows, 1,127 `rejudge_correct`** (73.18%,
   Wilson 70.9–75.3, consistent). Name that path in the report. Whether to commit a scrubbed copy of
   it to the public repo is a separate publish-guard decision (Polly does not add allow entries).
4. **README framing** (committed in `ebee5f6`, verify it survived): lead with citation integrity,
   tokens-per-answer and local-only; accuracy as a caveat, not a headline. Commonsense 63.6% is an
   accepted limit and stays stated.

---

# Appendix — what was verified when writing this brief

| claim | status |
|---|---|
| KU population 78 in `longmemeval_s_cleaned.json`; 74 eligible after excluding the 4 ids | verified by counting the dataset; Tes round 1 independently reproduced |
| literal 74 ids and the 20 pilot ids | produced by committed `eval/longmemeval/p17_ids.py` (dataset-only); reproduced 2026-11-10 |
| (d) as originally written keeps an answer session in the top 3 on 36/74; (c) on 71/74 (any answer session) / 68/74 (latest); pre-registered full-timestamp k=4 gives 67/74 latest, k=3 68/74, k=5 61/74, k=6 60/74, k=8 54/74, k=10 45/74 | measured 2026-11-10 by committed `eval/longmemeval/p17_recall_check.py` (`.venv/bin/python`, dataset-only, no model calls); output pasted in §B2 |
| 47.5 sessions/question, 28.4 with overlap>0 (min 7), 0 unparsed full timestamps, 2 answer sessions per question in all 74 | same committed script, same run |
| 26 of 74 questions have a same-day tie inside the relevance top 4; at k=4 the full-timestamp and date-only rules keep a different set on 6/74 (rev 3's 59/74 was a parse bug — `DAY_FMT` was passed the full timestamp and never parsed a single date; rev 4 fixes the parse and asserts 3,513/3,513 dates parse under both rules) | same committed script, re-run 2026-11-10 after the fix; output pasted in §B2 |
| the stray pre-freeze `ku_paired` run (pid 45392) is stopped and wrote no JSON | verified 2026-11-10 16:29 by `ps -p 45392` (gone) and `ls eval/results/ku-paired-20q.json` (absent) |
| all pre-freeze KU artifacts moved to `eval/results/ku-quarantine-20261110-pre-freeze/` with sha256s in `MANIFEST.md` | done and hashed 2026-11-10 16:30 (`shasum -a 256` output pasted into the manifest); `eval/results/ku-db/` is empty |
| the quarantined smoke brain is complete: 228 captures, 388 facts, sha256 `b6560579…c92c3` | read with `sqlite3` after the run stopped |
| `:8460` idle and serving `glm-5.3-flash`; `:1234` serving `text-embedding-nomic-embed-text-v1.5`; `:8889` `/health` = `spark-side-model` / DeepSeek-V4.1-Flash-1017 EXL3 EAQ v1 2.9bpw | verified 2026-11-10 16:29 |
| captures per KU question 209–236, mean 223 | computed from the dataset with the `session_chunks` 3,000-char rule |
| 7.5 s per extraction call; `71315a70` reached capture 196 of 228 in 24.4 min | measured 2026-11-10 15:50–16:14 by reading the in-flight brain read-only, with another agent sharing `:8460`; supersedes the 6.9 s figure in rev 1. The finished brain (228/228) is quarantined. |
| ≈9.3 h for the pilot, ≈34 h for 74 | derived from the row above; the §B4 rule replaces it with a measurement after 3 questions |
| `:8460` serving `glm-5.3-flash` and busy with the smoke at 16:14 | verified 2026-11-10 |
| `:1234` serving `text-embedding-nomic-embed-text-v1.5` | verified 2026-11-10 16:13 |
| `:8000` judge DOWN; `:8889` `/health` = `spark-side-model` / DeepSeek-V4.1-Flash-1017 EXL3 EAQ v1 2.9bpw | verified 2026-11-10 16:13 |
| `consolidate(conn, brain_id, max_mutation_rate=None)` and CLI default `0.2` | verified by reading `src/cairnstone/compile.py:845` and `src/cairnstone/cli.py:364` at `fdfb816` |
| `ku_paired.run_one` recompiles (`True`) and consolidates in place; never passes the rate; two arms only | verified by reading `eval/longmemeval/ku_paired.py` at `fdfb816` |
| `quote` is written as the **stripped** `str` slice; spans are bounds-checked as `str` indices | verified at `src/cairnstone/store.py:447-451` |
| `eval/harness.py` CLI has no `--db-dir` although `CairnBackend` accepts `db_dir` | verified at `fdfb816` |
| `fe71ff1` conv-26/conv-30 brains and the 11-07 baseline JSON exist at the paths in §B9 | verified 2026-11-10 (listing, mtimes 2026-11-07) |
| 1,540 rows / 1,127 correct in `rejudge-same-judge.jsonl` | verified 2026-11-10 by counting the file |
| no cron/launchd job runs cairnstone consolidation on this machine | verified 2026-11-10 (`crontab -l`, `~/Library/LaunchAgents`) |
| suite 133 at `fe71ff1` | verified by Tes, `reports/tes-review-4.md` |
| `_supersede_contradictions` was brain-wide at `fe71ff1` | verified by reading the function at `68280b9` |
| McNemar thresholds in §B6 | computed exactly (binomial, two-sided); verified by Tes round 1 |

## Constraints

- Interpreter `~/cairnstone/.venv/bin/python -m pytest -q`; bare `python3` is Xcode 3.9 and
  fails collection.
- Do not touch `reports/tes-review-4.md`.
- Do not weaken an existing assertion; if you rewrite one, say why in the report.
- Commit on `main` with `-c user.name=Polly -c user.email=polly@local`.
- Publish-guard: if it fires on push, stop and hand the hits to Tes; reword only your own report/brief
  text, never add allow entries.
- Polly commits; workers do not push.
- `src/cairnstone/compile.py` is shared with a parallel worker (uncommitted edits at 2026-11-10 16:14).
  The freeze waits for that worker's commit; §P9 adds to the same file, so sequence it after.
