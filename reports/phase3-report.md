DONE: Phase 3 implemented — hybrid retrieval with a cached local embedding endpoint, prefix-stable brief assembly with citation rendering (`src/cairn/retrieve.py`), and a `cairn` backend in `eval/harness.py` with a per-sample compiled-DB cache. Ran live against the local endpoints: cairn scores 75.0% at 4,341 mean context tokens vs full_context 83.3% / 15,043 and naive_rag 66.7% / 770 on the same 12 questions, with a 100% prompt-cache hit rate.

FILES:
- src/cairn/retrieve.py (new)
  - `search(conn, brain_id, query, k=10)` — hybrid: FTS5 over pages (`store.search_pages`) plus cosine similarity over fact and page text against the local embeddings endpoint (`http://127.0.0.1:1234/v1`, `text-embedding-nomic-embed-text-v1.5`). Fact score = cosine(fact, query) + 0.25 × FTS bonus of its page; page score = cosine + FTS bonus.
  - Embedding cache: `embeddings(subject_kind, subject_id, vector BLOB)` table created by `ensure_embedding_cache`; fact/page vectors keyed by row id, query vectors keyed by SHA-256 of the text, so unchanged text is never re-embedded (verified by test: second call makes zero endpoint requests).
  - Eligibility (P8): only `status='active'` and `duplicate_of IS NULL` facts; superseded facts are admitted only when `is_history_question` matches history phrasing ("used to", "previously", "no longer", …).
  - `build_brief(conn, brain_id, question, budget_tokens=4000)` → `(stable_text, question_text)`. The stable text is the compiled canonical content — page headers, active claims, each with a compact `[capture N, span a:b]` citation — and is question-independent by construction: the question never selects or orders stable content, so it is byte-identical across calls for the same brain (P9). Trimming order when over budget: drop low-ranked pages (fewest eligible facts first), then low-ranked facts (newest id first), then shorten quotes; citations are never dropped.
  - `render_citations(conn, fact_ids)` — expands facts to capture `source_ref` + quote + span for the evidence appendix.
- eval/harness.py
  - `CairnBackend`: compiles each LoCoMo conversation's captures into `eval/results/cairn-db/<sample>.db` once (compiled into a `.tmp` file and atomically renamed, so a crashed run cannot poison the cache) and reuses it on later runs; `--recompile` forces a rebuild. `full_context` and `naive_rag` behaviour untouched.
  - Answers use `build_brief`: stable content as its own leading `system` message, question as the `user` message — the message-boundary shape TensorFold requires for prefix reuse.
  - Per-row extras recorded via `row.update(result)` in `run_backend` (other backends' rows unchanged): `brief_tokens`, `facts_used`, `citations_used`, `superseded_used` (a superseded fact in the brief is flagged as a defect per P10 — none occurred).
- tests/test_retrieve.py (new) — 7 offline tests, fake embedding function, no network.
- reports/phase3-report.md — this file.

RAN:
- `PYTHONPATH=src python3 -m pytest -q`
- `PYTHONPATH=src:. python3 -m eval.harness --backend cairn --limit 1 --max-questions 12` (twice: first run compiled, second run reused the cached DB)
- Baseline numbers read from the existing `eval/results/2026-11-05-full_context.json` and `2026-11-05-naive_rag.json` (same 12 questions, same judge).

OUTPUT (pytest):
```
........................................                                 [100%]
40 passed in 0.18s
```
(26 pre-existing + 7 new retrieve tests + 7 store/compile = 40.)

OUTPUT (compile, first run):
```
=== cairn: 1 sample(s), 12 question(s) ===
  compiled conv-26: 419 captures, 449 facts, 16 pages, 0 failed captures
```

OUTPUT (eval table, n=12, local judge local-judge, answer model glm-5.3-flash @ 127.0.0.1:8460):

| backend | accuracy | questions | mean context tokens | mean latency (s) | cache hit |
|---|---|---|---|---|---|
| full_context | 83.3% | 12 | 15,043 | 3.15 | 0.917 |
| naive_rag | 66.7% | 12 | 770 | 2.38 | 0.0 |
| cairn | 75.0% | 12 | 4,341 | 1.66 | 1.0 |

Per-row cairn detail: `brief_tokens` was 3,978 on every row (byte-identical stable prefix across all 12 questions — the question-independence property held in practice), `citations_used` 121, `superseded_used` False on all rows, zero defect flags.

Does the thesis hold at n=12? **Directionally yes, not proven.** Cairn beats naive_rag (75.0% vs 66.7%) at ~5.6× its token cost but well under half of full_context's cost (4,341 vs 15,043 tokens), with the fastest mean latency (1.66 s) and a 100% prefix-cache hit rate — the prefix-stable brief did exactly what P9 claims. It does not yet beat full_context (75.0% vs 83.3%); the three misses were temporal questions where the compiled claims lost date precision the raw transcript retained. At 12 questions one flip is 8.3 points, so all three backends are within noise of each other; this measurement is directional only.

Next measurement: all 10 LoCoMo conversations, all ~1,986 questions, with per-category breakdowns — that is the n at which the cairn-vs-full_context gap becomes a real claim, and it directly reuses the per-conversation DB cache built here (compilation is the only incremental cost).

NOTES / DECISIONS:
- `build_brief`'s `question` parameter is accepted but deliberately not used to select or trim stable content: question-dependent trimming would change the cached prefix per question and defeat TensorFold's per-message-boundary reuse (measured 26 s → 0.12 s TTFT in docs/tensorfold-integration.md). Retrieval (`search`) is used instead for the per-question evidence appendix via `render_citations`, which lives outside the cached prefix.
- `store.py` and `compile.py` were NOT modified. The `embeddings` table is created by `retrieve.ensure_embedding_cache`, not by the store schema.
- The `embeddings` endpoint (127.0.0.1:1234), the answer endpoint (127.0.0.1:8460) and the judge (127.0.0.1:8889) were all up; no cloud calls anywhere (P12).

UNVERIFIED:
- The 100% cache-hit figure is `cached_tokens > 0` per request from the engine's `usage.prompt_tokens_details`; I did not separately verify the cached token count equals the full brief size per call.
- Accuracy at n=12 has ±~12-point swings per question flip; no confidence interval is meaningful at this n.
