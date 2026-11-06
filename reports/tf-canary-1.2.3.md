# TF 1.2.3 canary probes (independent review, t_4a185253, 2026-11-05)

Host: Mac Studio M3 Ultra, 512 GB. Model: `GLM-5.3-Flash-MLX-4bit-MTP@76add2a3` (stock), same files as prod.
Candidate: `tensorfold-native 1.2.3` on `127.0.0.1:8461` (`/health`: `"version": "1.2.3", "backend": "metal", "device": "Apple M3 Ultra"`).
Prod `:8460` (`tensorfold-native 1.0.7`, pid 21017) was left untouched throughout.

Raw evidence (every request/response pair, `/health` + `/metrics` before and after each probe, server logs):
`evidence/model-evals/tf-canary-1.2.3/` — `probe.py`, `port8461/p{1,2,3}.json`, `port8461/p4_spill.json`,
`serve-8461-identical-flags.log` (P1–P3), `serve-8461-spill.log` (P4).

## Timing and window

- The window had already closed when this card was claimed (21:30 UTC): the Phase 9 coding-agent worker (pid 41551) and the
  `eval.harness` (pid 42599) were running against `:8460`. The reviewer waited, and loaded 1.2.3 only once both had exited
  (22:06 UTC, two consecutive idle checks, `:8460` `live.connections 0`).
- Caveat: from about 22:13 to 22:23 an unidentified short-lived Python client (pid 85459, from a Hermes shell session)
  held one stream on `:8460`. Every probe's `other_port_before/after` field shows `:8460` at `connections 1` and
  decoding 5–74 tok/s. The two engines share one GPU, so **the absolute cold-prefill TTFTs below are not a clean
  1.2.3 speed number.** The P3/P4 conclusions rest on the cached/uncached contrast within one run (a 17–21 s cold
  prefill against 0.11–0.48 s on a hit), which that contention cannot explain.
- Install: release v1.2.3 (published 2026-11-05 17:36 UTC), saved in `runtimes/tensorfold-1.2.3/`.
  `shasum -a 256 -c tensorfold-1.2.3-macos-arm64.tar.gz.sha256` → `OK`, and every `SHA256SUMS` entry → `OK`. Nothing deleted.

Serve command for P1–P3 (flags identical to 1.0.7 prod):
```
HF_HUB_OFFLINE=1 tensorfold-1.2.3-macos-arm64/bin/tensorfold-native serve \
  "models/GLM-5.3-Flash-MLX-4bit-MTP@76add2a3" \
  --host 127.0.0.1 --port 8461 --name glm-5.3-flash --context 262144 --max-tokens 32768 \
  --parallel 4 --temperature 0 --no-update-check
```
Log: `GLM-5.3-Flash loaded in 57.4 s (180.6 GB of weights), context 262144 tokens, 4 streams` /
`176.9 GiB kept wired between requests` / `prompt cache ... of 16384 MiB` (16 GiB default budget).

## 1. Structured output — still HTTP 400 on Metal GLM

Request: `POST :8461/v1/chat/completions`, `{"model":"glm-5.3-flash","max_tokens":64,"messages":[user "Return a JSON object…"],
"chat_template_kwargs":{"enable_thinking":false},"response_format":{"type":"json_object"}}`. The same was sent with a strict
`json_schema` and with `guided_choice:["Paris","Lyon"]`.

Response (all three): `HTTP 400 {"error":{"message":"structured output (response_format and the guided_* fields) is not
supported by this engine yet","type":"invalid_request_error"}}`. Server log: `refused chatcmpl-…: structured output … not supported by this engine yet`.

`/health` live before/after: `connections 0, waiting 0` / `connections 0, waiting 0`.
Note: 1.2.3 ships `lib/libtfgrammar.dylib`, but GLM on Metal refuses before the grammar library is ever consulted. That
refusal is per engine, not a missing library.

**Verdict: yes, still 400 on 1.2.3. R2 (validate-and-retry) stays.**

## 2. Thinking control

Prompt: `What is 17 * 23? Answer with the number only.`, `max_tokens 2048`. All four requests returned HTTP 200, finish_reason `stop`.

| request field | content | reasoning_content chars | `tensorfold.enable_thinking` | `reasoning_effort` |
|---|---|---|---|---|
| none (default) | `391` | 73 | true | null |
| `chat_template_kwargs: {enable_thinking: false}` | `391` | 0 | **false** | `none` |
| top-level `thinking: {"type":"disabled"}` (1.2.1) | `391` | 0 | **false** | `none` |
| top-level `enable_thinking: false` | `391` | 73 | true | null |

`/health` live before/after: `connections 0` / `connections 0`.

**Verdict: `chat_template_kwargs.enable_thinking` still works, and the new top-level `thinking:{"type":"disabled"}` also
works on 1.2.3. Top-level `enable_thinking` is still silently ignored, as on 1.0.7. Keep `chat_template_kwargs`, which is
portable; the `thinking` switch is a valid alternative on ≥1.2.1 only.**

## 3. Message-boundary prefix reuse

Stable system message = instruction plus a 260-line synthetic ledger (8,3xx tokens). Only the later user message changes.
`max_tokens 24`, thinking off, streamed with `include_usage`. Sent sequentially, so one stream on `:8461`.

| case | prompt_tokens | cached_tokens | TTFT (s) |
|---|---|---|---|
| a. cold, Q1 | 8320 | 0 | 17.387 |
| b. same system, **changed** Q2 | 8321 | **8306** | **0.121** |
| c. same system, changed Q3 | 8322 | 8306 | 0.128 |
| d. system message's **tail** changed (one line appended inside it), Q1 | 8327 | **0** | 17.320 |
| e. exact repeat of a | 8320 | 8306 | 0.115 |

Server log for b: `prompt cache: 8321 tokens, resumed at 8306`. For d: `resumed at 0, kept 1`.
`/health` live before/after: `connections 0` / `connections 0`. `/metrics` after: `prompt_cache_states 2`, `prefix_cache_hits_total 24918`.

**Verdict: message-boundary reuse holds on 1.2.3 (8306/8321 cached, TTFT 17.4 s → 0.12 s). An edit inside the system
message gets no reuse: all 8,327 tokens were prefilled again, so reuse inside a message was not observed. Cairn's
message-boundary rule stands.**

## 4. `--spill-gib` / memory-pressure admission and eviction re-ask

- **`--spill-gib` is gone from the 1.2.3 CLI.** `serve --help` does not list it. The flag also passes argparse
  (`serve /nonexistent --spill-gib 8` reaches the model-path error, whereas `--bogus-flag` gets
  `unrecognized arguments`), so it is probably a hidden alias. Whether it does anything on its own was not isolated.
  On 1.2.3 the documented disk tier is `--prompt-cache-disk DIR`.
- **`/health` exposes nothing new for pressure or admission.** The keys are `status, model, model_ids, max_batch_size,
  warming, memory{active,cache,peak,limit}, live{connections,waiting,decode_tokens_per_second,prefill_tokens_per_second},
  version, backend, device`. `memory` is populated on 1.2.3 (`limit 358400000000`); on 1.0.7 it is `{}`. `version`,
  `backend` and `device` are also new against 1.0.7's `/health`. `/metrics` has no pressure or spill counters (only
  `prompt_cache_states/bytes`, `prompt_tokens_cached_total` and `prefix_cache_*`). The memory-pressure governor is only
  visible in the logs. It did not fire: free memory stayed ≥28%.

Eviction test, restarted on `:8461` with the same flags plus
`--prompt-cache-gib 1 --prompt-cache-disk "tf-canary-1.2.3-spill" --spill-gib 8`.
Log: `prompt cache: device budget not reported, disk tier at tf-canary-1.2.3-spill`.
Conversation A (9,617 tokens), then 9 unrelated ~9.6k-token conversations to overflow the 1 GiB RAM budget, then A re-asked.

| step | cached_tokens | TTFT (s) | server log |
|---|---|---|---|
| A turn 1 | 0 | 20.738 | `resumed at 0, kept 1` |
| A re-ask (warm) | 9603 | 0.115 | `resumed at 9603` |
| flood 0–8 | 0 each | 20.04–20.99 | RAM budget full at flood 5 (`7 states, 985 MiB … of 1024 MiB`); `evicted 1…5` |
| **A re-ask after flood** | **9603** | **0.476** | `imprint: read 9603 tokens from disk (316 MiB in 345 ms)` / `resumed at 9603 … evicted 5, refused 0, failed 0` |

Each state was written to disk in the background (`imprint: 9603 tokens on disk … 316 MiB`). Disk used: 3.2 GiB on
Extreme Pro scratch. `/health` live before/after: `connections 0` / `connections 0`. `memory.active` went from 190.68 GB to 191.90 GB.

**Verdict: an evicted conversation survives a re-ask. `cached_tokens` came back as 9603/9617, read from disk in 345 ms
(TTFT 0.48 s against 20.7 s cold), with 0 refused and 0 failed. `/health` shows `memory` and identity fields but no
pressure or admission state, and `--spill-gib` is undocumented on 1.2.3 (use `--prompt-cache-disk`). What this did
not show: whether `A` was itself among the evicted states (the log counts evictions but does not name them; the
`imprint: read … from disk` line implies it was), and the governor under real memory pressure.**

## Consequences for Phase 9 / promotion

- None of the four probes blocks a 1.2.3 swap. R2, `chat_template_kwargs` and the message-boundary rule all carry over unchanged.
- If the harness wants admission state, it should take `/health.memory` and `/metrics` `prompt_cache_*` / `prefix_cache_*`.
  No pressure field exists to record.
- Not done here, still deferred: the paired accuracy canary (`--answer-url` on `:8461`) and a clean prefill/decode speed
  comparison at matched, single-tenant concurrency. Promoting onto `:8460` needs Ged.
- After the probes `:8461` was stopped (`pgrep tensorfold-1.2.3` → none). The 1.2.3 install and the 3.2 GiB spill dir
  remain; neither has been deleted.
