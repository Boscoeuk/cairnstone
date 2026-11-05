# eval — Phase 0 harness

Measures memory quality on LoCoMo (Snap Research, ACL 2024; research use) by comparing two
backends. It exists so every later compile-policy decision is scored instead of guessed.

- **full_context** — puts the entire conversation in a stable leading message (the reference
  baseline).
- **naive_rag** — chunks the conversation, embeds with the local
  `text-embedding-nomic-embed-text-v1.5` endpoint, retrieves top-5 chunks, answers from them.

## Run

```bash
python3 -m eval.harness --baseline --limit 1 --max-questions 12
python3 -m eval.harness --backend naive_rag --limit 2 --max-questions 40
```

`--limit` bounds conversations, `--max-questions` bounds questions (default 25; `0` = all).
Bound both: a full 3-conversation run is ~600 questions and takes hours on local hardware.

## Measured 2026-11-05 (12 questions, one conversation)

| backend | accuracy | mean context tokens | mean latency | prompt cache hit |
|---|---|---|---|---|
| full_context | 83.3% | 15,043 | 3.15 s | 91.7% |
| naive_rag | 66.7% | 770 | 2.38 s | 0% |

Engine: TensorFold `tensorfold-native` 1.0.7, GLM-5.3-Flash-MLX-4bit-MTP, greedy, `--parallel 4`,
Apple M3 Ultra (Mac Studio, 512 GB). Answerer `glm-5.3-flash`, judge `local-judge`.

**Read this with care.** n=12 is a smoke test, not a result. The gap is directional, not
statistical. The full_context latency is dominated by one cold prefill (~30 s); the other 11
questions hit the prompt cache at ~0.1 s TTFT. naive_rag shows 0% cache hits because each
question retrieves different chunks.

Two real failure modes are already visible in the rows, both relevant to the compile layer:

1. **Relative time.** "When did Caroline go to the LGBTQ support group?" → gold `7 May 2023`,
   predicted `Yesterday`. A compiled page must anchor dates absolutely; raw transcript retrieval
   invites relative answers.
2. **Local judging.** Numbers here are judged by `local-judge`, not GPT-judged, so they are
   comparable in shape to published LoCoMo figures, not identical to them.

## Output

`eval/results/<UTC-date>-<backend>.json` with per-question rows (question, gold, predicted,
verdict, ambiguity flag, category, context tokens, latency, sources, and TensorFold engine
telemetry: tokens/s, prefill, TTFT, cached tokens) plus aggregates and the dataset, answerer,
judge and engine identity.

## What the numbers mean

- **accuracy** — fraction judged CORRECT. Category 5 (adversarial) rewards refusing to invent.
- **mean context tokens** — the cost axis, from the endpoint `usage` block.
- **prompt cache hit** — fraction of calls reusing a cached prompt. This is a TensorFold-specific
  metric; see `docs/tensorfold-integration.md`. It is only non-zero when the stable content is
  its own leading message.

## Endpoints (local only, OpenAI-compatible)

| role | URL | model |
|---|---|---|
| answerer | `http://127.0.0.1:8460/v1` | `glm-5.3-flash` |
| judge | `http://127.0.0.1:8889/v1` | `local-judge` |
| embeddings | `http://127.0.0.1:1234/v1` | `text-embedding-nomic-embed-text-v1.5` (768d) |

`Authorization: Bearer local`, 180 s timeout, 2 retries. No cloud call is made anywhere.

## Requirements

Python 3.9+ and `requests`. The dataset must exist at `eval/datasets/locomo10.json`; it is
gitignored and never modified by the harness.
