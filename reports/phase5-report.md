# Phase 5 report — scale the measurement, close the atomic-fact gap

## DONE

Implemented phase 5 per `docs/phase5-brief.md`: (A) scope-qualified result filenames and
median-latency reporting with outlier flags, (B) atomic attribute facts in the extractor with
offline tests, (C) all three backends run at `--limit 2 --max-questions 60` against the live
local endpoints.

## FILES

- `eval/harness.py` — `save_results` now writes `<date>-<backend>-s<limit>-q<max_questions>.json`
  (scope in the name; prior files are never overwritten). `run_backend` flags rows slower than
  5x the median as `latency_outlier`. `aggregate` reports `median_latency_s` and
  `latency_outlier_count` alongside the mean. `comparison_table` shows median before mean.
- `src/cairn/compile.py` — `EXTRACTION_SYSTEM` now requires atomic attribute facts for people
  (relationship status, location, occupation, age, family role) whenever the capture implies
  them, with direct inference only under a supporting quote ("no quote, no fact"). The quote
  rule (P2) is unchanged and still enforced by `locate`/`write_facts`.
- `tests/test_compile.py` — three new offline tests: prompt contains the attribute rules;
  the Caroline scenario ("plans to become a single parent", "moved to Austin", "nursing job")
  compiles 3 accepted facts with `uncited_facts == []`; an invented fact with no supporting
  quote is rejected.
- `eval/results/2026-11-05-{cairn-b600,full_context,naive_rag}-s2-q60.json` — run evidence.
- `reports/phase5-report.md` — this file.

## RAN

```
PYTHONPATH=src:. python3 -m pytest tests/ -q
PYTHONPATH=src:. python3 -m eval.harness --backend cairn --limit 2 --max-questions 60 --brief-budget 600
PYTHONPATH=src:. python3 -m eval.harness --backend full_context --limit 2 --max-questions 60
PYTHONPATH=src:. python3 -m eval.harness --backend naive_rag --limit 2 --max-questions 60
```

Test output: `49 passed in 0.34s`.

## RESULTS (n=60, 2 conversations, local-judged — not GPT-judged)

| backend | accuracy | questions | mean ctx tokens | median latency (s) | mean latency (s) | latency outliers | cache hit |
|---|---|---|---|---|---|---|---|
| cairn (brief budget 600) | **70.0%** | 60 | 922 | 2.17 | 2.24 | 0 | 0.0 |
| full_context | 53.3% | 60 | 15,044 | 0.32 | 0.82 | 1 | 0.0 |
| naive_rag | 43.3% | 60 | 845 | 2.32 | 2.23 | 0 | 0.0 |

Accuracy by category:

| backend | commonsense | multi-hop | temporal |
|---|---|---|---|
| cairn | 55.6% | 39.1% | **100%** |
| full_context | 77.8% | 56.5% | 42.9% |
| naive_rag | 100% (n=9) | 26.1% | 39.3% |

Retrieval/answering split (phase-4 diagnostic): cairn 12 retrieval failures, 6 answering
failures; full_context 28 retrieval failures, 0 answering failures; naive_rag 34 retrieval
failures, 0 answering failures. Median latency: cairn 2.17 s, full_context 0.32 s,
naive_rag 2.32 s. Outlier count: 1 (full_context; the mean-without-median trap the phase-4
review flagged is now reported correctly).

## Verdict

At this scope (2 conversations, 60 questions) cairn beats both naive_rag and full_context —
70.0% vs 43.3% and 53.3% — and the margin is far larger than one question: +16 and +10
questions respectively, where one question is 1.67 points.

## Honest caveats

- Still only 2 conversations; the category cells are small (naive_rag's 100% commonsense is
  n=9). The direction is now consistent across 60 questions, but several-conversation coverage
  remains open.
- Cairn loses to full_context on commonsense and multi-hop; its win is carried by temporal
  questions (100% vs 42.9%), which is exactly where cited, date-resolved facts should win.
- The phase-4 atomic-fact fix is tested offline; the live run's 12 cairn retrieval failures
  were not individually re-audited this phase.

## UNVERIFIED

Nothing material. All three runs completed against the live local endpoints (answer
127.0.0.1:8460, judge 127.0.0.1:8889, embeddings 127.0.0.1:1234); no cloud calls.
