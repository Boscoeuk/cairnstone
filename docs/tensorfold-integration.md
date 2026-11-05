# TensorFold integration

Cairnstone targets **TensorFold** (Ash Hart, `github.com/ashhart/TensorFold`, Apache-2.0) as its
inference substrate. This is not incidental — it is a design dependency, and the pairing is
genuinely complementary:

| | TensorFold | Cairnstone |
|---|---|---|
| Makes | inference fast | context small and true |
| Serves | tokens | cited facts |
| Memory kind | weights (`--slide` / Living Weights, experimental) | compiled Markdown pages with sources |

TensorFold compacts history to survive a context window; Cairnstone compiles it to preserve truth.
Both reduce what has to be re-sent. Cairnstone's briefs are the *better* half of that trade when the
content must stay auditable.

## Measured on this machine (2026-11-05)

Engine: `tensorfold-native 1.0.7`, `GLM-5.3-Flash-MLX-4bit-MTP`, `--context 262144`,
`--max-tokens 32768`, `--parallel 4`, `--temperature 0`, Apple M3 Ultra (Mac Studio, 512 GB, Metal), served on
`127.0.0.1:8460`.

| Measurement | Value |
|---|---|
| Decode rate, short generation | 29–45 tok/s (reported in `tensorfold.tokens_per_second`) |
| Cold prefill, 4,588-token prompt | 9.19 s (≈500 tok/s prefill) |
| Time to first token, cold | 31.1 s |
| Same prompt repeated | prefill **0.086 s**, TTFT **0.11 s**, `cached_tokens: 4579` |
| Prefix cache | **active and reported** via `usage.prompt_tokens_details.cached_tokens` |

Prefix reuse is real, measurable, and exposed per request. This is the single most important
performance fact for Cairnstone: a **stable prefix** turns a 31 s cold start into 0.11 s.

## Prefix reuse is per message boundary (measured 2026-11-05)

This is the single most important integration fact. Reuse is keyed at a **message boundary**,
not on arbitrary text prefixes:

| Shape | Result |
|---|---|
| Stable text in its own leading `system` message, volatile question in a later message | cached 11,152 tokens, TTFT **26.1 s → 0.12 s** across *different* questions |
| Whole context plus question concatenated into one `user` message | cached 0 on a changed question; only an exact repeat hits |
| Exact prompt repeated | cached (e.g. 45,531 of 45,534 tokens), TTFT 90 s → 0.04 s |

Consequence: a brief that is merely "prefix-compatible" is worthless. The stable compiled
content must occupy a distinct leading message, byte-identical across calls. Measured effect
is roughly a 200x reduction in time to first token, which changes what is economically possible
for an agent that asks several questions of the same memory.

## API constraints discovered (engine 1.0.7)

1. **No structured output.** `response_format` (`json_object` and `json_schema`) and the
   `guided_*` fields return HTTP 400: *"structured output (response_format and the guided_*
   fields) is not supported by this engine yet"*. Cairnstone must therefore validate model output
   client-side and repair/retry rather than relying on grammars.
2. **Thinking is controlled by `chat_template_kwargs.enable_thinking`**, not by a top-level
   `enable_thinking` field (which is silently ignored). With thinking off, `reasoning_content`
   is empty and `content` is populated; with it on, the answer arrives in `reasoning_content`
   and `content` can be empty at low `max_tokens`. Budget tokens accordingly.
3. **Telemetry is available per call** in the `tensorfold` object: `engine`, `tokens_per_second`,
   `prefill_seconds`, `time_to_first_token`, `enable_thinking`, `exact_mode`.
4. **Live admission state** is available at `GET /health` and `GET /`:
   `live.connections`, `live.waiting`, `max_batch_size`, `decode_tokens_per_second`.
5. `tensorfold-native capabilities --json` lists every serve flag. Notable: `--prompt-cache-gib`,
   `--parallel`, `--no-thinking`, `--thinking-budget`, `--reasoning-effort`, `--compact-at`,
   `--compact-keep`, `--compact-memory`, `--slide`, `--learn`, `--metrics-open`, `--dashboard`,
   `--loop-guard`, `--drafter`.

## Design rules that follow

- **R1 — prefix-stable briefs.** Canonical ordering, stable page identifiers, no timestamps or
  volatile counters inside the cached prefix. Briefs are assembled so the shared portion is
  byte-identical across calls. Cache hit rate is a first-class metric in the eval ledger.
- **R2 — no constrained decoding.** Every extraction result is schema-validated; invalid output
  is repaired with a bounded retry, then rejected. Model output is untrusted data.
- **R3 — thinking budget by task.** Extraction and classification run with thinking off
  (`chat_template_kwargs`); conflict resolution and summarisation may enable it.
- **R4 — admission control.** The nightly compile pass reads `/health` and yields when
  `live.connections` approaches `--parallel` (4 on this host). Compile batches never starve
  an interactive user.
- **R5 — engine ledger.** Every compile and eval call records engine, tokens/s, prefill, TTFT
  and cached tokens. Results are reported against named hardware, matching TensorFold's own
  "inference, measured" practice. No abstract token claims.
- **R6 — complementary to Living Weights.** Cairnstone is the cited, editable, auditable half.
  `--slide` / `--learn` is the parametric half. Cairnstone is the natural selector for what is
  worth sliding into weights once that path is stable.

## Upstream opportunities (do not act without Ged's approval)

- Structured output / grammars in the engine would remove Cairnstone's repair loop and are exactly
  what a memory compiler needs.
- A memory-shaped endpoint or a documented prefix-stability convention would make Cairnstone-style
  briefs first-class.
- If Cairnstone ever contributes to TensorFold, use **Agent Traffic Control** (`atc`) and the
  contributor skill at `docs/recipes/SKILL.md`, per their CONTRIBUTING rules.
