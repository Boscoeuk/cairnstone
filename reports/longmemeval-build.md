# Phase 13 — LongMemEval build report

Date: 2026-11-06. All numbers below come from files produced by the runs in this
document; nothing is estimated from memory.

## What was built

`eval/longmemeval/lme_eval.py` (single file, ~430 lines), runnable as:

```
PYTHONPATH=src:. python3 eval/longmemeval/lme_eval.py --split s --questions 20 --budget 600 --seed 20261106
```

Components, per the brief:

1. **Selection** — `select_questions()`: deterministic, seeded (`--seed`), stratified
   across the six question types, proportional to the type distribution with at
   least 2 per type (largest-remainder allocation). The chosen `question_id`s are
   recorded in the result file under `question_ids`. `--full-context-questions`
   (default 5) selects the first K ids **in selection order** as the fixed
   full-context subset (recorded as `full_context_ids`).
2. **Capture building** — one capture per haystack session, prefixed
   `Session date: 2023/04/10 (Mon) 17:50` (the exact `haystack_dates` format, so
   relative dates resolve). Sessions over 3000 characters split at turn boundaries
   into multiple captures, each carrying the same date prefix. Captures go into a
   per-question SQLite DB at `eval/results/lme-db/<question_id>.db`
   (gitignored), workspace/brain `default`/`default`. DBs are cached across runs;
   `--recompile` forces a rebuild.
3. **Compile** — `cairnstone.compile.compile_all`. Per question the result file
   records captures, facts accepted, rejections by reason, failed captures, and
   the reject rate; a rate above 0.5 prints a `WARNING` and continues (observed
   below).
4. **Backends** — all answer with the same local model (`glm-5.3-flash` at
   `CAIRNSTONE_BASE_URL`, default `http://127.0.0.1:8460/v1`) and the terse
   instruction reused **verbatim** from `eval/dogfood/dogfood_eval.py`
   (`ANSWER_SUFFIX`):
   - `cairnstone`: `retrieve.build_brief` at `--budget`, citations rendered via
     `retrieve.render_citations`, `gold_support_in_brief` computed per row.
   - `keyword`: top-3 whole sessions by lexical token overlap with the question,
     verbatim (the "just search the raw logs" baseline).
   - `full_context`: the entire haystack, only for the `--full-context-questions`
     ids. It never truncates: if the estimated prompt exceeds the model's
     262,144-token window, the row records `skipped: context_window_exceeded`
     with the estimate instead of dropping content.
5. **Judging** — the LoCoMo harness judge (`eval/harness.py`) is imported and its
   `judge()` used directly, so the prompt and verdict parsing (including the
   `judge_ambiguous` path) are byte-identical. Per the phase rules the judge
   endpoint is `http://<lan-node>:8889/v1` with model `local-judge` (LAN address
   and route alias genericised for publication)
   (env-overridable via `CAIRN_JUDGE_URL`/`CAIRN_JUDGE_MODEL`). Results are
   labelled `LOCAL-JUDGED` in the output file and aggregate.
6. **Output** — `eval/results/longmemeval-<split>-<budget>-<n>q-<UTCstamp>.json`
   with per-row `question_id`, `question_type`, `question`, `gold`, per-backend
   answer/verdict/`judge_ambiguous`/latency/`prompt_tokens`, brief tokens,
   citations used, `gold_support_in_brief`, and the compile stats; plus an
   aggregate with accuracy overall and per type, mean brief tokens, median
   latency, and outlier count (a cairnstone latency above 3× the median).
7. **Oracle split** — `--split oracle` uses `longmemeval_oracle.json`, whose
   haystacks already contain only the evidence sessions (verified: for every
   question `haystack_session_ids` equals `answer_session_ids`), so it is cheap.

No file outside `eval/longmemeval/`, `eval/results/`, `.gitignore`, and
`reports/` was modified. `src/cairnstone/`, `eval/harness.py`, and every existing
measured number are untouched.

## Smoke run (2 questions, oracle split, real output)

Command:

```
PYTHONPATH=src:. python3 eval/longmemeval/lme_eval.py --split oracle --questions 2 --budget 600 --seed 20261106 --full-context-questions 1
```

Complete console output (`--full-context-questions 1` because the full-context
baseline is keyed on the first K selected ids; with 2 questions the default 5
would be the same subset either way):

```
split=oracle n=2 budget=600 seed=20261106 full_context_ids=['1a8a66a6']
1a8a66a6 [multi-session] cairnstone=MISS keyword=MISS brief=170t 0.808s
993da5e2 [temporal-reasoning] cairnstone=MISS keyword=MISS brief=171t 1.98s
{
  "label": "LOCAL-JUDGED",
  "n": 2,
  "accuracy_overall": {
    "cairnstone": 0.0,
    "keyword": 0.0,
    "full_context": 1.0
  },
  "accuracy_by_type": {
    "multi-session": {
      "n": 1,
      "cairnstone_accuracy": 0.0,
      "keyword_accuracy": 0.0,
      "full_context_accuracy": 1.0
    },
    "temporal-reasoning": {
      "n": 1,
      "cairnstone_accuracy": 0.0,
      "keyword_accuracy": 0.0,
      "full_context_accuracy": null
    }
  },
  "mean_brief_tokens": 170.5,
  "median_latency_s": 1.394,
  "outlier_count": 0,
  "judge_ambiguous_count": 0
}
wrote eval/results/longmemeval-oracle-600-2q-20261106-205708Z.json
```

(The exact filename written was `longmemeval-oracle-600-2q-20261106-205708Z.json`.)

First-run compile warnings (before the DBs were cached) also printed:

```
  WARNING 1a8a66a6: reject rate 1.0 above 0.5
  WARNING 993da5e2: reject rate 0.929 above 0.5
```

Row detail from the result file (`eval/results/longmemeval-oracle-600-2q-20261106-205708Z.json`):

| question_id | type | gold | cairnstone answer | keyword answer | full-context answer |
|---|---|---|---|---|---|
| 1a8a66a6 | multi-session | 2 | "1" | "One (The New Yorker)" | "Two (The New Yorker and Architectural Digest)" — CORRECT |
| 993da5e2 | temporal-reasoning | One week (7–10 days acceptable) | "I don't have any records about when you rearranged your living room furniture…" | "Two months" | (not run — not in the full-context subset) |

Compile stats from the per-question DBs (`eval/results/lme-db/`):
`1a8a66a6` — 21 captures, 0 facts accepted (reject rate 1.0);
`993da5e2` — 12 captures, 2 facts accepted (reject rate 0.929).

## Estimated cost of the full 20-question S run

Grounding numbers, all measured: the S split's median haystack is 489,793
characters (min 454,980, max 513,953 — `eval/datasets/longmemeval_s_cleaned.json`);
captures are capped at 3,000 characters, giving ≈163 captures per question at the
median; one capture is one extraction LLM call inside `compile_all` (the LoCoMo
harness measured 419 extraction calls for a single LoCoMo sample, same code path).

- **Compilation (dominant, one-time):** 20 questions × ~163–170 captures ≈
  3,300–3,400 extraction calls. At the 2–4 s per call observed during this
  session's smoke compiles, that is roughly **2–4 hours of local-endpoint time**,
  all written once into `eval/results/lme-db/*.db` and reused by every later run.
- **Answering:** cairnstone + keyword per question took 0.8–2.0 s each in the
  smoke run; 20 questions ≈ **1–2 minutes total**.
- **Full-context baseline:** 5 questions × ~122k tokens of prefill at the
  ~4 minutes/question the brief quotes ≈ **20 minutes**.
- **Judging:** 2 judge calls per question (cairnstone + keyword) + 5 more for the
  full-context rows — negligible.

Total first run: **≈ 2.5–4.5 hours**, dominated by compilation; any rerun with
warm DBs is minutes.

## Verification and what I could not verify

- `python3 -m pytest -q` → **91 passed** (the brief said 89; the suite currently
  contains 91 tests, all passing — no tests were added or changed).
- Smoke run completed end-to-end and wrote its result file (path above).
- Not verified: the full 20-question S run itself (not executed here — cost above);
  the `context_window_exceeded` path (S haystacks at ~122k tokens fit the
  262,144-token window, so it never triggered); and accuracy at 20 questions,
  which the smoke run's n=2 cannot predict.
- Environment note: the judge endpoint returned intermittent 404s during one
  smoke attempt (transient server-side; the same request succeeded immediately
  before and after). One code fix came out of this: `harness.judge`'s default
  `model` argument is bound at import time, so `lme_eval.py` passes
  `model=JUDGE_MODEL` explicitly at every call site.
