# Phase 17 brief — consolidation knowledge-update test

Written by Polly, 2026-11-10. Reviewed by Tes **before any run**; Tes re-checks the result before it
is called accepted. No measurement run has been made yet: the only execution on this code is one
aborted 1-question smoke (`eval/longmemeval/ku-smoke.log`), which is not a result.

Two parts, in this order:

- **Part A — pre-work.** Close `reports/tes-review-4.md` F1–F4 and re-establish the citation
  invariant at the frozen code. The KU test exercises the contradiction path directly, so it cannot
  run on code whose contradiction scope is undocumented and untested.
- **Part B — the experiment.** Does one nightly consolidation pass make compiled memory more
  correct on knowledge-update questions?

Decisions recorded here are Polly's and are final for this phase; the implementation must not
re-litigate them. Evidence and the defects themselves are Tes's, in `reports/tes-review-4.md`
(committed at `68280b9`, do not edit that file).

---

# Part A — pre-work (all of it before the run starts)

## P1 — F1: contradiction scope

`_supersede_contradictions` built one `claims` dict across the whole brain. At `fe71ff1` 20 of 43 new
supersessions/flags paired facts on **different pages**, and several are plainly wrong
(`projects/alpha` "first CI run failed" superseded by a `projects/beta` fact; phase-1 vs phase-2
acceptance; conv-26 vs conv-30 counts).

**Decision:** the scan resets its comparison state **per page**, as policy P6 and the phase-16 brief
already specify. Do not invent an entity-key scheme in this phase.

**Known limitation, to be documented, not fixed here:** some genuinely correct pairs cross pages —
user facts split between `misc/user` and `people/user`, and the Fitbit tenure supersession. They stay
unresolved. Record them with their evidence in `docs/compile-policies.md` under P6 and in
`reports/phase17-report.md`. A future phase may key on entity rather than page; that is out of scope.

Required test: a fact on page A must be unable to supersede or flag a fact on page B, with the
counter-case (same page, genuinely contradicting) still superseding.

**Consequence for Part B that must be stated in the report:** if the KU arm shows no gain, page scope
is one candidate cause — a LongMemEval update that lands on a different page from the stale claim
cannot be resolved. The mechanism diagnostic in §B7 exists to tell those cases apart.

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

F4 is on the KU critical path (the arm depends on state/event classification), so it lands with
P1–P3 if it can be tested cleanly. If it cannot, the run proceeds without it and the report names F4
as an unclosed limitation — it is not a reason to delay the overnight window by more than one pass.

## P5 — citation-integrity re-check at the frozen code (required, not optional)

The `1,640 / 1,640` figure in the README and `reports/tes-review-4.md` was measured on the
**2026-11-07** `eval/dogfood/session.db`. It is not evidence about today's HEAD and must not be
re-quoted as if it were.

Write `eval/quote_integrity_audit.py` (new; deterministic, read-only, no model calls) that, for each
database passed on the command line, verifies for **every** fact row:

```
facts.quote == captures.content[span_start:span_end]   # byte-equal
```

and reports per database: facts checked, mismatches (with fact id, capture id, span), facts with a
missing capture or out-of-range span, and the sha256 of the database file. Run it at the frozen SHA
on:

1. `eval/dogfood/session.db` (continuity with the 1,640 figure — same database, new code);
2. every LongMemEval brain in `eval/results/lme-db/*.db`;
3. every KU brain produced by the run in `eval/results/ku-db/*.db` (§B7).

Report the counts with the database identity, file hash and date. A single mismatch blocks
acceptance. Add a test that mutates one `facts.quote` in a scratch copy and asserts the audit fails
(it must be able to fail).

## P6 — suite state

The suite is **133 passed at `fe71ff1`** (phase 16, accepted — `reports/tes-review-4.md`, reproduced
by Tes). `115 passed` is the count at `d73b6ae` and belongs only to pre-fix trees; do not attach it to
`fe71ff1`. The pre-work commit must report its own measured pass count (`.venv/bin/python -m pytest
-q`, run from the repository root; bare `python3` is Xcode 3.9 and fails collection).

## P7 — collateral probe (evidence that F1+F3 did what they claim)

Re-run Tes's collateral probe on the same corpus (27 real databases, ~10.5k active facts:
`eval/dogfood/session.db`, the conv-26 and conv-30 DBs, and the 22 LongMemEval result DBs) on
**SQLite backup copies**, two passes, and report superseded / flagged / duplicate-linked counts
against her baselines: `fe71ff1` = 3 / 40 / 57; `d73b6ae` = 0 / 9 / 33. The point is that the false
flags fall while the three correct supersessions survive — or are lost only under the documented
cross-page limitation. P11 must still halt a runaway pass.

---

# Part B — the experiment

## B1 — the claim under test

Cairnstone's product claim is that a nightly consolidation pass improves a memory over time. The
first test of that claim is knowledge-update: an earlier value is stated, a later session changes it,
and the correct answer is the current value.

**Thesis holds only if arm (b) beats arm (a) AND arm (b) beats arm (d).** Anything else is reported as
"not shown at this n", never as "consolidation does not work".

## B2 — arms

One brain per question, built once, then four answers from it. Compile happens once; every arm uses
the same answerer.

| arm | definition |
|---|---|
| (a) | Cairnstone as the compiler left it — `retrieve.build_brief(conn, brain_id, question, budget_tokens=600)`, **no** consolidation call. Note: `compile_all` itself runs dedupe/supersession, so (a) is "post-compile, pre-nightly-pass"; (b)−(a) isolates the nightly pass only. |
| (b) | The same brain after **one** nightly pass: `compile.consolidate(conn, brain_id, max_mutation_rate=0.2)` — the function `cairnstone consolidate` calls, with the CLI's default rate (`src/cairnstone/cli.py`, `--max-mutation-rate` default `0.2`). Verified 2026-11-10: there is **no installed cron or launchd job** for cairnstone on this machine; the CLI command is the nightly entry point, so (b) is that command's code path. Record the returned counts and any `PolicyHalt`. |
| (c) | Keyword retrieval, as committed in `eval/longmemeval/lme_eval.py::keyword_backend`: top-3 whole sessions by length-normalised lexical overlap, verbatim, each prefixed with its session date. |
| (d) | Keyword retrieval **ranked newest-first**: new `keyword_newest_backend` in the same module. Candidate sessions are those with overlap > 0 (same tokenisation and stopword list as (c)); order by parsed session date **descending** (unparseable dates last), tie-break overlap descending; take 3; identical prompt, identical `ANSWER_SUFFIX`, identical session-date prefix. This is the "recency beats relevance" baseline. |

Fairness note to carry into the report: (c) and (d) read raw sessions, which already carry absolute
session dates; Cairnstone briefs now carry capture dates too (commit `ebe5f6`). Both sides have date
information, so a Cairnstone win is not a date-format artefact.

Do not change extraction, retrieval ranking, `build_brief` beyond the committed date fix, or the
citation invariant as part of this phase.

## B3 — questions

- Dataset: `eval/datasets/longmemeval_s_cleaned.json`, split `s` (full haystack — not `oracle`;
  an oracle haystack would flatter both keyword arms).
- Knowledge-update population: **78** questions (verified count, 2026-11-10).
- **Excluded as previously used in tuning or smoke — 4 ids:**
  `08e075c7`, `0f05491a`, `2133c1b5_abs` (the three KU questions measured in the phase-13 20-question
  run, `eval/results/longmemeval-s-600-20q-20261107-162311Z.json`, and quoted in the README as
  "1 of 3"), and `71315a70` (the 1-question smoke of 2026-11-10).
- **Eligible: 74 questions.** Order by `question_id` ascending (fixed, deterministic); seed
  `20261110` for the pilot subset. Pilot subset = the first 20 of a seeded sample of the 74, and it is
  a subset of the full 74 so extending later is not re-sampling.
- If only the pilot runs, every table and sentence must be labelled **PILOT (n=20)**. A pilot cannot
  accept the thesis; it can only show direction and mechanism.

## B4 — budget and the 20-vs-74 decision (measure, then decide)

Grounding numbers, all measured:

- one extraction call per capture; captures per question on this split are 209–236 (mean 223 over the
  74 eligible questions, computed from the dataset with the `lme_eval.session_chunks` 3,000-character
  rule);
- **measured 2026-11-10 15:50:30 → 16:04:00 on question `71315a70` (`eval/results/ku-db/71315a70.tmp`,
  read live): 118 of 228 captures compiled in 13.5 minutes — 6.9 s per extraction call**, against the
  2–4 s the phase-13 build report recorded. Caveat: another agent was using `:8460` at the same time,
  so 6.9 s is a pessimistic figure, not a clean benchmark.

At 6.9 s/capture:

| scope | compile calls | wall time at 6.9 s/call |
|---|---|---|
| 20 (pilot) | ~4,460 | ≈ 8.5 h |
| 74 (full) | ~16,500 | ≈ 32 h |

**Decision, written before the run:** the 74-question set does **not** fit a single overnight window
at the measured rate. The overnight run is therefore the **20-question PILOT** (≈ 8.5 h), labelled
PILOT everywhere, and the remaining 54 are compiled over following nights — compile DBs are cached per
question (`eval/results/ku-db/<qid>.db`), so extension costs only answering and judging. If the
measured rate after the first 3 pilot questions projects the full 74 inside the remaining window, run
all 74 instead; otherwise stop at 20. Do not silently shrink to whatever number finished.

Disk: ≈ 1 MB per brain, so ≈ 75 MB for the full set; check ≥ 2 GB free before starting (285 GB free
at 2026-11-10 16:00).

## B5 — freeze

Write `eval/longmemeval/ku-phase17-config.json` and commit it **before** the first question runs. It
must contain, verbatim:

- the frozen code SHA (the pre-work commit, after P1–P6 are green) and `git status` clean;
- dataset path, split, eligible question ids, seed, pilot size, question order;
- `budget_tokens = 600`;
- answerer: endpoint URL, model id, engine identity as reported by the endpoint, `temperature=0`,
  `max_tokens=120`, and the `ANSWER_SUFFIX` string unchanged;
- judge: endpoint URL and model id as reported by the endpoint;
- consolidation parameters (`max_mutation_rate=0.2`);
- the success criterion text from §B6, the McNemar thresholds, and the arm definitions;
- the runtime decision rule from §B4.

The result JSON must record a sha256 of that config plus every one of those fields, so the freeze is
inspectable after the fact. **One answerer, one judge, one engine for all four arms.** No mid-run
substitution: if an endpoint changes identity mid-run, stop and restart the run rather than mix
identities.

## B6 — pre-registered success criterion

Primary (both required, exact two-sided McNemar on paired per-question outcomes):

1. (b) vs (a): `p < 0.05` with discordant pairs in the direction "a wrong → b right" outnumbering
   "a right → b wrong";
2. (b) vs (d): `p < 0.05` in the same direction.

Report, for every pair among {a,b,c,d}: both-correct, both-wrong, and the two discordant counts, with
the exact p value. (c) is descriptive, not gating.

Minimum detectable effect (exact McNemar, two-sided α = 0.05, computed 2026-11-10):

| n | discordant pairs D | minimum split that reaches p < 0.05 |
|---|---|---|
| 74 | 6–8 | D:0 (all one direction) |
| 74 | 10 | 9:1 |
| 74 | 15 | 12:3 |
| 74 | 20 | 15:5 |
| 20 (pilot) | 6 | 6:0 |
| 20 (pilot) | 8 | 8:0 |

So at n=74 this test can confirm only a **large** effect (roughly a 4:1 gain-to-loss ratio among
discordant pairs); at n=20 only a near-total win. State this next to the result, not in a footnote.
Report Wilson 95% intervals per arm — at n=74 a point estimate near 50% carries ±11 points.

## B7 — mechanism diagnostic (required; without it a null result is uninterpretable)

Per question, record:

- consolidation counts (`duplicates_linked`, `superseded`, `flagged`) and any `PolicyHalt`;
- whether ≥1 superseded fact was **in the pre-consolidation brief** (the stale claim the answerer
  actually saw) — this is the mechanism firing;
- whether the superseding fact was selected into the post-consolidation brief;
- `active_before` / `active_after` fact counts, `brief_tokens` per Cairnstone arm,
  `gold_support_in_brief` per Cairnstone arm, judge verdict + `judge_ambiguous` + `finish_reason`,
  and both answers verbatim.

If **no** question had a stale fact in its brief superseded, the report must say "mechanism not
exercised on this sample", not "no effect".

## B8 — gates (all checked immediately before the first question; log the result of each)

1. **:8460 idle.** `/v1/models` answers and reports the answerer model; a 1-token completion returns;
   `pgrep -f "eval/(harness|lme_eval|ku_paired)"` is empty. At 2026-11-10 15:50–16:04 the 1-question
   smoke held the endpoint (118 of 228 captures still compiling at 16:04), so re-check, do not assume.
2. **Judge healthy.** The judge endpoint answers `/v1/models`, and a 3-call sanity probe in which the
   gold answer is submitted as the answer must return CORRECT 3/3. Record the judge identity
   verbatim. **Verified 2026-11-10 15:55: `http://127.0.0.1:8000/v1` (the documented default) was
   DOWN.** The 1-question smoke therefore pinned `CAIRN_JUDGE_URL=http://spark-side:8889/v1` with
   `CAIRN_JUDGE_MODEL=spark-side-model`; that is the route this phase uses unless `:8000` is up, and
   whichever is used must be recorded and identical for all arms and for §B9.
3. **No cloud.** Every endpoint URL is loopback or `the LAN address`. Assert it in the harness and record
   the URLs in the result file.
4. **No recompile** of the LoCoMo per-sample DBs (§B9); `--recompile` would cost hours for no reason.

## B9 — post-run: the LoCoMo date-format re-measure (separate result, separate claim)

The committed date fix (capture dates in records + the `### Time` resolution rule, `ebe5f6`) changes
answer format. Re-measure LoCoMo **after** the KU run, at the same frozen SHA, same answerer and
judge:

```
CAIRN_JUDGE_URL=<pinned> CAIRN_JUDGE_MODEL=<pinned> PYTHONPATH=src:. python3 -m eval.harness \
  --backend cairnstone --limit 2 --questions-per-sample 75 --max-questions 150 \
  --brief-budget 600 --judge-model <pinned>
```

(no `--recompile`; the conv-26/conv-30 brains already exist under `eval/results/cairnstone-db/`).
Pair it question-by-question against `reports/locomo-phase15.md` / the 11-07 run at `fe71ff1`
(same 150 questions, seed and selection) and report: overall accuracy, temporal accuracy,
outside-temporal accuracy, discordant pairs and McNemar p, mean context tokens.

Report it as **a formatting fix, not a retrieval gain**: the mechanism is that relative-date answers
now resolve to absolute dates, and the pre-registered expectation is a temporal-category gain with no
change outside temporal questions. If outside-temporal accuracy moves, say so — that would mean the
change is doing something else.

## B10 — report requirements

`reports/phase17-report.md` plus the artifacts, with every number measured, not asserted:

- n, frozen SHA, `git status` clean, config sha256;
- answerer: endpoint, model, engine identity, temperature, max_tokens;
- judge: endpoint, model, blind-by-construction statement (the judge prompt carries question, gold
  and answer only — never an arm label; arms are judged independently, never side by side), sanity
  probe result;
- artifact paths: `eval/longmemeval/ku-phase17-config.json`,
  `eval/results/ku-paired-b600-q<n>-<UTC stamp>.json`, per-question brains under
  `eval/results/ku-db/`, the quote-integrity audit output, the LoCoMo result file;
- per-arm table: accuracy, Wilson 95% CI, mean/median prompt tokens, latency, judge-ambiguous count;
- all six pairwise discordant tables with exact McNemar p;
- the §B7 mechanism diagnostic, including questions where consolidation fired and where it did not;
- the §P5 integrity counts and the §P7 collateral counts;
- the runtime decision actually taken (74 or 20) and why;
- **what was not verified.**

## B11 — stop conditions

- Judge endpoint down or identity changed → stop; do not substitute mid-run.
- `:8460` busy with another eval → wait; do not interleave (prefix-cache and latency measurements
  become meaningless).
- `PolicyHalt` on a brain → record it, treat that question's "after" as unchanged, and continue; do
  not raise the rate to force a mutation.
- Any non-local endpoint → stop.
- P1–P3 not closed and green → do not start the run.

---

# Part C — wording corrections that must land with this phase

1. **Test count.** 133 at `fe71ff1`; 115 at `d73b6ae`. Do not attach 115 to `fe71ff1`.
2. **Phase numbering.** Phase 16 = `fe71ff1` (accepted, `reports/tes-review-4.md`). This phase is 17.
   The date fix comments in `src/cairnstone/retrieve.py` and the `ku_paired.py` docstring say
   "Phase 16" — relabel them phase 17. Comment-only change; no behaviour change.
3. **README accuracy row.** If an accuracy row is kept, it uses the **1,540-question LoCoMo run:
   73.2%, Wilson 95% 70.9–75.3** — not the 150-question 78%. Verified 2026-11-10: 1,540 = all ten
   conversations minus the 446 category-5 adversarial questions (1,986 − 446); 1127/1540 = 73.18%
   with Wilson 70.9–75.3, consistent with the quoted figure. **Verified gap:** no JSON in
   `eval/results/` carries n=1540 (`2026-11-06-cairnstone-b600-ps75-s2-q150…` is the 150-question
   run), so the row must name the artifact path where that run lives, or the row is dropped.
4. **README framing** (committed in `ebe5f6`, verify it survived): lead with citation integrity,
   tokens-per-answer and local-only; accuracy as a caveat, not a headline. Commonsense 63.6% is an
   accepted limit and stays stated.

---

# Appendix — what was verified when writing this brief

| claim | status |
|---|---|
| KU population is 78 in `longmemeval_s_cleaned.json`; 74 eligible after excluding 4 ids | verified by counting the dataset, 2026-11-10 |
| captures per KU question 209–236, mean 223 | computed from the dataset with the `session_chunks` 3,000-char rule |
| 2–4 s per extraction call (phase-13 build report) | measured then; superseded by the 2026-11-10 smoke rate below |
| 6.9 s per extraction call; 118/228 captures in 13.5 min on `71315a70` | measured 2026-11-10 15:50:30–16:04:00 by reading `eval/results/ku-db/71315a70.tmp` live, with another agent sharing `:8460` |
| ≈ 8.5 h for the 20-question pilot, ≈ 32 h for 74 | derived from the two rows above; the §B4 rule replaces it with a measurement after 3 questions |
| `:8460` serving `glm-5.3-flash` | verified 2026-11-10 15:55 |
| `:8000` judge DOWN; `:8889` serves `spark-side-model`; `:8890` serves `local-stock` | verified 2026-11-10 15:55 |
| no cron/launchd job runs cairnstone consolidation on this machine | verified 2026-11-10 (`crontab -l`, `~/Library/LaunchAgents`) |
| suite 133 at `fe71ff1` | verified by Tes, `reports/tes-review-4.md` |
| 1,540q = 1,986 − 446 adversarial; 73.2% / 70.9–75.3 | verified from `locomo10.json` counts and a Wilson calculation; the run's own artifact is **not** in this repo |
| `_supersede_contradictions` was brain-wide at `fe71ff1` | verified by reading the function at `68280b9` |
| McNemar thresholds in §B6 | computed exactly (binomial, two-sided), 2026-11-10 |

## Constraints

- Interpreter `~/cairnstone/.venv/bin/python -m pytest -q`; bare `python3` is Xcode 3.9 and
  fails collection.
- Do not touch `reports/tes-review-4.md`.
- Do not weaken an existing assertion; if you rewrite one, say why in the report.
- Commit on `main` with `-c user.name=Polly -c user.email=polly@local`.
- Publish-guard: if it fires on push, stop and hand the hits to Tes; reword only your own report/brief
  text, never add allow entries.
- Polly commits; workers do not push.
