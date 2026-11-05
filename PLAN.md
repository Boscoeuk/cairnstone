# PLAN

Owner: the maintainer (project manager, sole Hermes agent). Workers: coding agents (oh-my-pi)
driving local models only. No cloud inference at any point.

## Ground rules

1. Every phase ends with a **verifiable artifact** and a command that reproduces the result.
2. No phase is "done" on an agent's assertion. the maintainer runs the acceptance command.
3. The compile policy is the product. CRUD, MCP wrapping and SDKs are plumbing.
4. Eval numbers are always reported with: dataset, subset size, judge model, context tokens,
   and date. Never quote a number without them.

## Phases

### Phase 0 — harness (current)
Build `eval/harness.py`: ingest a dataset conversation into a pluggable memory backend, answer
questions, judge with a local model, report accuracy / context tokens / latency.
Acceptance: runs end-to-end on LoCoMo (10 samples) against two baselines (full-context, naive
chunk RAG) and writes `eval/results/<date>-<backend>.json` + a markdown table.

### Phase 1 — core store
SQLite schema: workspaces, brains, captures (immutable, hashed), pages, page_versions,
facts (each with source capture id + span), buckets, links, change feed. FTS5 index.
Acceptance: `pytest` green; capture→page→version round-trip; deleting a capture is refused
while facts cite it (or cascades explicitly).

### Phase 2 — compile pipeline
Capture → extraction → page placement → fact writing with citations → scoring.
Nightly evolution pass: merge duplicates, supersede, flag contradictions, retire stale.
Acceptance: compile 100 captures from the LoCoMo corpus with zero uncited facts; every fact
resolves to a real capture span; contradiction fixture produces a supersede event, not an
overwrite.

### Phase 3 — retrieval
Hybrid search (FTS + vector), page graph, prompt-index endpoint (a cited brief under a token
budget). Acceptance: beats the phase-0 naive-RAG baseline on LoCoMo at equal or lower context
tokens.

### Phase 4 — interfaces
MCP server (stdio + HTTP), CLI, REST API. Acceptance: an MCP client can capture, search and
read a page; CLI does the same; both covered by tests.

### Phase 5 — ingestion and docs
Importers (Markdown folder, Obsidian vault, ChatGPT/Claude export), document extraction
(PDF/DOCX/text), audio optional. Acceptance: a real vault imports with citations intact.

## Risks

- Local model quality: GLM-5.3-Flash at ~45 tok/s and the secondary local model at ~29 tok/s are the
  ceiling for compile quality. The pipeline must degrade gracefully — schema-constrained
  extraction, retries, and deterministic fallbacks — rather than trusting free-form prose.
- Throughput: compiling a corpus is token-bound. Batched extraction, caching, and a small
  local model for yes/no judgements (not a 5.3B model) are required to keep it affordable.
- Judge bias: local judging inflates agreement. Mitigate with a hand-checked subset.

### Phase 6 — TensorFold depth (ongoing, feeds every phase)
Cairnstone is TensorFold-native. `docs/tensorfold-integration.md` holds the measured engine facts and
the design rules (prefix-stable briefs, no constrained decoding, thinking budget, admission
control, engine ledger). Acceptance: the eval ledger reports engine, tok/s, prefill, TTFT and
cached tokens per call; brief assembly is byte-identical for the cacheable prefix across two
runs (test).
