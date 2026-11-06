# Phase 13 — LongMemEval

Build and run a LongMemEval evaluation for Cairnstone. Do not change the compiler, the retriever,
the LoCoMo harness or any existing measured number. New code lives under `eval/longmemeval/`.

## Data

`eval/datasets/longmemeval_s_cleaned.json` (500 questions) and `longmemeval_oracle.json`
(500 questions, evidence sessions only). Both are lists of objects with:
`question_id`, `question_type` (multi-session, temporal-reasoning, knowledge-update,
single-session-user, single-session-assistant, single-session-preference), `question`,
`answer`, `question_date`, `haystack_dates` (per session), `haystack_sessions` (list of
lists of {role, content}), `answer_session_ids`.

S haystacks are ~490k characters (~122k tokens) over ~48 sessions. That cost drives every
design decision below.

## What to build

`eval/longmemeval/lme_eval.py`, runnable as
`PYTHONPATH=src:. python3 eval/longmemeval/lme_eval.py --split s --questions 20 --budget 600 --seed 20261106`

1. **Selection.** Deterministic, seeded, stratified across the six question types: 20 questions
   total, allocated proportionally to the type distribution but at least 2 per type. Record the
   chosen question_ids in the result file so the run is reproducible. Add `--full-context-questions`
   (default 5) selecting a fixed subset of those ids for the expensive baseline.
2. **Capture building.** One capture per haystack session, prefixed with the session date line so
   relative dates resolve ("Session date: 2023/04/10 (Mon) 17:50"). Sessions longer than 3000
   characters split at turn boundaries into multiple captures, each carrying the same date prefix.
   Write captures into a per-question SQLite DB under `eval/results/lme-db/<question_id>.db`
   (gitignored), workspace/brain `default`/`default`.
3. **Compile.** Use `cairnstone.compile.compile_all`. Report per question: captures, facts accepted,
   rejections by reason, failed captures. A reject rate above 0.5 should be reported, not fatal.
4. **Backends**, all answering with the same local model and the same terse instruction already
   used in `eval/dogfood/dogfood_eval.py` (reuse it verbatim so results are comparable):
   - `cairnstone`: `retrieve.build_brief` at the requested budget, citations rendered.
   - `keyword`: top-3 sessions by lexical overlap with the question, verbatim, ~same token order
     of magnitude. This is the "just search the raw logs" baseline.
   - `full_context`: the whole haystack, only for `--full-context-questions` ids. Expect ~4 minutes
     of prefill per question; do not run it on all 20.
5. **Judging.** Same local judge and same verdict parsing as the LoCoMo harness (`eval/harness.py`),
   including the `judge_ambiguous` path. Label results LOCAL-JUDGED.
6. **Output.** `eval/results/longmemeval-<split>-<budget>-<n>q-<UTCstamp>.json` containing per-row
   (question_id, type, backends' answers, verdicts, brief tokens, latency, citations used,
   gold_support_in_brief where computable) and an aggregate with accuracy overall and per type,
   mean tokens, median latency, outlier count.
7. **Oracle split.** `--split oracle` uses only the evidence sessions (cheap). Support it.

## Rules

- Local endpoints only: `CAIRNSTONE_BASE_URL` (default `http://127.0.0.1:8460/v1`, model
  `glm-5.3-flash`) for answering/compiling, judge model `local-judge` at
  `http://<lan-node>:8889/v1`. No cloud.
- Never silently truncate a haystack: if the full-context prompt exceeds the model's window, say so
  in the row rather than dropping content.
- Every claim in your report must cite a number from a file you produced.

## Deliverables

- `eval/longmemeval/lme_eval.py` (+ any small helpers).
- A smoke run on 2 questions of the oracle split that actually completes, with its output pasted in
  the report.
- `reports/longmemeval-build.md`: what you built, the smoke output, the estimated cost of the full
  20-question S run, and anything you could not verify.
- `python3 -m pytest -q` must still pass (89 tests) — you are adding no tests unless you touch
  shared code, which you should not.
