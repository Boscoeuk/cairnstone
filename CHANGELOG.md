# Changelog

## 0.1.0 — 2026-11-05

First tagged release of the cairnstone memory compiler.

Previously developed under the working name "cairn"; renamed to Cairnstone before the first
public release. Dated records in `reports/` and `docs/phase*-brief.md` keep the working name
because they are historical evidence, not current documentation.

### What works

- **Capture → compile → retrieve pipeline.** `cairnstone ingest` stores immutable captures;
  `cairnstone compile` calls a local model endpoint to extract cited facts into Markdown pages
  about people, projects, decisions and customers; `cairnstone search`, `cairnstone brief`,
  `cairnstone page`, `cairnstone history` and `cairnstone export` retrieve and inspect them.
- **Citation chain.** Every fact cites a capture id and character span; the verbatim quote
  is copied at write time and facts whose quote cannot be located in their capture are
  rejected, not guessed at.
- **Compile policies.** Capture immutability, no uncited facts, contradiction supersession,
  prefix-stable briefs (`docs/compile-policies.md`).
- **CLI + MCP server.** `cairnstone` console script (stdlib + requests only) and a stdio MCP
  server (`pip install ".[mcp]"`) exposing capture, compile, search, brief, get_page,
  fact_history and export_markdown. Verified against `mcp` 2.x and 1.x.
- **81 tests**, passing offline; tests that need the local model endpoint skip cleanly
  when it is unreachable.
- **Measured results** (Phase 9, 150 LoCoMo questions, local-judged): cairnstone 77.3% accuracy
  at 1,276 mean context tokens vs 53.3% / 13,278 for full context and 45.3% / 932 for
  naive chunk-RAG. Small sample (2 conversations), local judge — see `eval/README.md`.

### What does not work / known limits

- **No cloud inference, by design.** `compile` and `brief` require the local endpoint
  (`CAIRN_BASE_URL`, default `http://127.0.0.1:8460/v1`); if it is unreachable they exit
  non-zero. There is no fallback.
- **Local-judged eval numbers.** Not comparable to GPT-4o-judged published figures; small
  sample.
- **Structured output unavailable** on the reference engine (TensorFold 1.2.3 rejects
  `response_format`); the compiler validates JSON and rejects facts rather than repairing
  them silently.
- Commonsense and multi-hop questions remain the weak spot versus the full-context baseline.
