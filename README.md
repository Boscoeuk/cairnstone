# Cairnstone

A **local-first memory compiler for AI agents**. It reads what a team or a single operator
produces — conversations, notes, documents, agent session logs — and compiles it into
Markdown pages about people, projects, decisions and customers, where **every fact carries a
citation to the exact source it came from**. A compile pass merges duplicates, supersedes
stale facts, and flags contradictions without destroying history.

This is an independent open-source reimplementation of the *capability* of commercial
"living memory" products (livingbrain.com by ChatAndBuild). It is not a clone of their code,
their UI, or their pricing model — it is a clone of the **compile-and-retrieve capability**,
built to run entirely on local hardware.

## Hard constraints

- **No cloud inference.** Every model call goes to an endpoint on the local network:
  - compiler/answerer: `CAIRNSTONE_BASE_URL` (default `http://127.0.0.1:8460/v1`), model
    `CAIRNSTONE_MODEL` (default `glm-5.3-flash`)
  - judge (evaluation only): configured in `eval/harness.py`
  - the legacy `CAIRN_*` spellings are still honoured, so an existing shell keeps working
  - embeddings: `http://127.0.0.1:1234/v1` (`text-embedding-nomic-embed-text-v1.5`, 768d)
- If an endpoint is unreachable the tool fails loudly. There is no cloud fallback.
- Data stays on disk. SQLite + Markdown export. Nothing leaves the machine.
- Apache-2.0.

## Install

```bash
pip install .            # runtime: stdlib + requests only
pip install ".[mcp]"     # adds the `mcp` package for the MCP server
```

Requires Python 3.10+. After install, the `cairnstone` console script is on your PATH
(equivalently: `python3 -m cairnstone.cli`).

## CLI

```bash
cairnstone init --db brain.db
cairnstone ingest --db brain.db --kind note --source "chat-log-1" --file notes.txt
cairnstone compile --db brain.db                       # calls the local model endpoint
cairnstone consolidate --db brain.db                   # nightly pass: dedupe + supersede + flag (no model)
cairnstone search --db brain.db "Caroline" --limit 5
cairnstone brief --db brain.db "Where does Caroline live?" --budget 4000
cairnstone page --db brain.db people/caroline
cairnstone history --db brain.db 42                    # one fact's citation + change events
cairnstone export --db brain.db --out ./export         # one Markdown file per page
```

`init`, `ingest`, `consolidate`, `search`, `page`, `history` and `export` need no model.
`compile` compiles only captures that have not been compiled before (`consolidate` re-runs
the model-free merge/supersede/flag pass over the whole brain at any time). `compile` and
`brief` call the local endpoint configured by `CAIRNSTONE_BASE_URL` (default
`http://127.0.0.1:8460/v1`) and `CAIRNSTONE_MODEL` (default `glm-5.3-flash`); if it is
unreachable they exit non-zero with a clear message — there is no cloud fallback.
Every command prints a machine-greppable `ok:` / `error:` line and exits non-zero on failure.

## MCP server

`src/cairnstone/mcp_server.py` is a stdio MCP server exposing `capture`, `compile`, `search`,
`brief`, `get_page`, `fact_history` and `export_markdown`. If the `mcp` package is not
installed it degrades gracefully: a clear one-line error instead of a traceback. Configure it
in an MCP client (e.g. Claude Desktop) with:

```json
{
  "mcpServers": {
    "cairnstone": {
      "command": "python3",
      "args": ["-m", "cairnstone.mcp_server"],
      "env": {
        "CAIRNSTONE_DB": "/path/to/brain.db",
        "CAIRNSTONE_BASE_URL": "http://127.0.0.1:8460/v1",
        "CAIRNSTONE_MODEL": "glm-5.3-flash"
      }
    }
  }
}
```

## Citation model

Every answer traces to evidence through one chain:

**claim → capture → span → verbatim quote.**

A fact (the claim) cites a capture by id and character span; the verbatim quote is copied
from that span at write time and a fact whose quote cannot be located in its capture is
rejected, not guessed at. `cairnstone history` shows the chain for any fact; `cairnstone brief` and
the Markdown export print it under every claim.

## Measured results

150 LoCoMo questions across 2 conversations, recompiled and re-measured on the current code
(2026-11-06; result `eval/results/2026-11-06-cairnstone-b600-ps75-s2-q150-130032Z.json`):

| backend | accuracy | mean context tokens | median latency |
|---|---|---|---|
| **cairnstone (compiled memory)** | **78.0%** | **1,276** | 2.89 s |
| full context | 53.3% | 13,278 | 2.73 s |
| naive chunk-RAG | 45.3% | 932 | 2.71 s |

The two baselines do not depend on the compiler, so their numbers carry over from the same
150-question scope. By category, cairnstone wins temporal questions decisively (88.5% vs 32.8%
full context) and multi-hop (70.0% vs 57.5%), loses single-hop narrowly (73.7% vs 76.3%) and
commonsense (63.6% vs 72.7% full context and 90.9% for naive chunk-RAG). 13 questions were
retrieval failures and 20 answering failures; no latency outliers.

**Most of the headline gap is an answer-format effect, not a retrieval advantage.** Of full
context's 41 wrong temporal answers, 27 give a relative date ("Yesterday", "Next month") where the
gold wants the absolute one (e.g. gold "7 May 2023", answer "Yesterday"). The full-context prompt
does include the session dates but asks only for "a short phrase", with no instruction to resolve
relative dates; the compiled facts carry absolute dates. Outside temporal questions (89 of the 150)
the two are level: cairnstone 63/89 (70.8%) against full context 60/89 (67.4%) — a tie within noise
at this sample size. So read the 24.7-point headline as mostly a date-resolution capability rather
than a general one; rerunning full context with an explicit date-resolution instruction is the test
that would settle it.

**Read this with care.** The numbers are **local-judged** (a local model as judge, not
GPT-4o), so they are comparable in shape to published LoCoMo figures, not identical to them.
They cover **2 conversations** of the dataset — a small sample, not a benchmark result. Against
the previous measurement on the same 150 questions this run is 0 lost and 1 gained (exact McNemar
p = 1.0), so 78.0% is **unchanged within noise**, not an improvement.
Commonsense questions remain the weak spot: the compiled pages hold explicit claims, and questions
needing inference beyond them fail more often than either baseline (63.6% against 72.7% full
context and 90.9% naive chunk-RAG). Full methodology and per-phase measurements: `eval/README.md`
and `reports/`.

## Development

```bash
python3 -m pytest -q        # full suite; the live smoke test skips when the endpoint is down
```

The design policies (capture immutability, no uncited facts, contradiction supersession,
prefix-stable briefs, local-only endpoints) are documented in `docs/compile-policies.md`.

The MCP server is verified over a real stdio session against `mcp` 2.x (where `FastMCP` was renamed
to `MCPServer`); it also resolves the 1.x class. Structured output is unavailable on the reference
engine (TensorFold 1.2.3 rejects `response_format`), so the compiler validates JSON and rejects
facts rather than repairing them silently.

## Licence

Apache-2.0. See `LICENSE`.
