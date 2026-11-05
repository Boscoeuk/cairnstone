# Cairn

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
  - compiler/answerer: `glm-5.3-flash` → `http://127.0.0.1:8460/v1` (`glm-5.3-flash`)
  - second worker / judge: `local-judge` → `http://127.0.0.1:8889/v1` (`local-judge`)
  - embeddings: `http://127.0.0.1:1234/v1` (`text-embedding-nomic-embed-text-v1.5`, 768d)
- If an endpoint is unreachable the tool fails loudly. There is no cloud fallback.
- Data stays on disk. SQLite + Markdown export. Nothing leaves the machine.
- Apache-2.0.

## Install

```bash
pip install .            # runtime: stdlib + requests only
pip install ".[mcp]"     # adds the `mcp` package for the MCP server
```

Requires Python 3.10+. After install, the `cairn` console script is on your PATH
(equivalently: `python3 -m cairn.cli`).

## CLI

```bash
cairn init --db brain.db
cairn ingest --db brain.db --kind note --source "chat-log-1" --file notes.txt
cairn compile --db brain.db                       # calls the local model endpoint
cairn search --db brain.db "Caroline" --limit 5
cairn brief --db brain.db "Where does Caroline live?" --budget 4000
cairn page --db brain.db people/caroline
cairn history --db brain.db 42                    # one fact's citation + change events
cairn export --db brain.db --out ./export         # one Markdown file per page
```

`init`, `ingest`, `search`, `page`, `history` and `export` need no model. `compile` and
`brief` call the local endpoint configured by `CAIRN_BASE_URL` (default
`http://127.0.0.1:8460/v1`) and `CAIRN_MODEL` (default `glm-5.3-flash`); if it is
unreachable they exit non-zero with a clear message — there is no cloud fallback.
Every command prints a machine-greppable `ok:` / `error:` line and exits non-zero on failure.

## MCP server

`src/cairn/mcp_server.py` is a stdio MCP server exposing `capture`, `compile`, `search`,
`brief`, `get_page`, `fact_history` and `export_markdown`. If the `mcp` package is not
installed it degrades gracefully: a clear one-line error instead of a traceback. Configure it
in an MCP client (e.g. Claude Desktop) with:

```json
{
  "mcpServers": {
    "cairn": {
      "command": "python3",
      "args": ["-m", "cairn.mcp_server"],
      "env": {
        "CAIRN_DB": "/path/to/brain.db",
        "CAIRN_BASE_URL": "http://127.0.0.1:8460/v1",
        "CAIRN_MODEL": "glm-5.3-flash"
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
rejected, not guessed at. `cairn history` shows the chain for any fact; `cairn brief` and
the Markdown export print it under every claim.

## Measured results

Phase 9 (150 LoCoMo questions, 2 conversations, 1,276 mean context tokens):

| backend | accuracy | mean context tokens |
|---|---|---|
| **cairn (compiled memory)** | **77.3%** | **1,276** |
| full context | 53.3% | ~15,000 |
| naive chunk-RAG | 45.3% | — |

**Read this with care.** The numbers are **local-judged** (a local model as judge, not
GPT-4o), so they are comparable in shape to published LoCoMo figures, not identical to them.
They cover **2 conversations** of the dataset — a small sample, not a benchmark result.
Commonsense and multi-hop questions remain the weak spot: the compiled pages hold explicit
claims, and questions needing inference beyond them fail more often than the full-context
baseline. Full methodology and per-phase measurements: `eval/README.md` and `reports/`.

## Development

```bash
python3 -m pytest -q        # full suite; the live smoke test skips when the endpoint is down
```

The design policies (capture immutability, no uncited facts, contradiction supersession,
prefix-stable briefs, local-only endpoints) are documented in `docs/compile-policies.md`.
