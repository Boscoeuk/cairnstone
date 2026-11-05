# Phase 10 report — make cairn a usable open-source tool

DONE: CLI + MCP server + packaging + README shipped; 81 tests pass; CLI verified end to end against a fresh temp DB with the live local endpoint.

## Files changed

- `LICENSE` — Apache-2.0, full text (fetched from apache.org).
- `pyproject.toml` — package `cairn`, `requires-python = ">=3.10"`, runtime dep `requests` only, optional extra `mcp`, console script `cairn = cairn.cli:main`.
- `src/cairn/cli.py` — new. Subcommands `init`, `ingest`, `compile`, `search`, `brief`, `page`, `history`, `export`. Every command prints a machine-greppable `ok:`/`error:` line and exits non-zero on failure.
- `src/cairn/mcp_server.py` — new. stdio MCP server (`FastMCP`) with tools `capture`, `compile`, `search`, `brief`, `get_page`, `fact_history`, `export_markdown`. Degrades gracefully without the `mcp` package (see below).
- `tests/test_cli.py` — new. 12 tests: offline coverage for every model-free command, no-cloud-fallback proofs for `compile`/`brief`, and one live smoke test gated on endpoint reachability.
- `README.md` — replaced the stub: what cairn is, install, CLI examples, MCP config snippet, citation model, measured results table, honest caveats, no-cloud constraint.
- `reports/phase10-report.md` — this file.

The compiler (`src/cairn/compile.py`), retriever (`src/cairn/retrieve.py`) and eval prompt were not changed.

## Design decisions

- **Single default brain.** The CLI stores everything in one workspace/brain (`default`/`default`) so `--db PATH` is the only address the user needs.
- **Endpoint pre-flight.** `extract()` converts any chat failure into a generic `ExtractError`, so an unreachable endpoint would look like bad model output. `compile` and `brief` therefore check `{CAIRN_BASE_URL}/models` first and exit non-zero with "local endpoint ... unreachable ... no cloud fallback (policy P12)".
- **P2 enforcement in the CLI.** `compile` loops `compile_capture` per capture and stops with a non-zero exit when the cumulative reject rate exceeds `--max-reject-rate` (default 0.25), before dedupe/supersede.
- **Search degradation.** `retrieve.search` needs the local embedding endpoint. When it is unreachable the CLI warns on stderr and falls back to FTS over pages (policy P12 allows degrading to fewer facts; it never reaches for another model). The retriever itself is untouched.
- **MCP graceful degradation.** `import cairn.mcp_server` works without `mcp`; `python3 -m cairn.mcp_server` prints `error: The 'mcp' package is not installed. Install it with: pip install "cairn[mcp]"` and exits 1. The tool bodies (`tool_capture`, `tool_search`, ...) are plain functions testable without the package.

## Verification

### Test suite

```
RAN: python3 -m pytest -q
OUTPUT: 81 passed in 3.39s   (69 pre-existing + 12 new; live smoke test ran against the real endpoint)
```

### End to end against a fresh temp DB (real output)

```
RAN: python3 -m cairn.cli init --db $DB
OUTPUT: ok: initialised brain id=1 workspace='default' at /var/folders/.../tmp.o5Quwd6XPq/e2e.db

RAN: python3 -m cairn.cli ingest --db $DB --kind note --source chat-log-1 --file /tmp/n1.txt   (x3)
OUTPUT: ok: capture id=1 kind=note source='chat-log-1' bytes=64
        ok: capture id=2 kind=note source='chat-log-2' bytes=96
        ok: capture id=3 kind=note source='chat-log-3' bytes=67

RAN: python3 -m cairn.cli compile --db $DB
OUTPUT: ok: compiled captures=3 accepted=4 rejected=0 duplicates_linked=0 superseded=0 failed_captures=[]

RAN: python3 -m cairn.cli search --db $DB "Caroline" --limit 3
OUTPUT: ok: page id=1 score=2.0000 Caroline
        ok: fact id=2 score=1.0111 Caroline lives in Berlin
        ok: fact id=1 score=0.9062 Caroline started hormones in March 2026

RAN: python3 -m cairn.cli brief --db $DB "Where does Caroline live?"
OUTPUT: answer: Berlin
        citations:
        - [capture chat-log-1 span 10:37] Caroline started hormones in March 2026 -- "I started hormones in March"
        - [capture chat-log-1 span 42:62] Caroline lives in Berlin -- "I live in Berlin now"
        ...
        ok: brief facts=4

RAN: python3 -m cairn.cli brief --db $DB "What pet does Caroline have?"
OUTPUT: answer: Caroline has a golden retriever named Biscuit.

RAN: python3 -m cairn.cli page --db $DB people/caroline
OUTPUT: ok: page id=1 path=people/caroline bucket=people
        - Caroline lives in Berlin [capture 1 span 42:62] ...

RAN: python3 -m cairn.cli history --db $DB 2
OUTPUT: ok: fact id=2 status=active page=people/caroline
        citation: capture 1 span 42:62
        quote: "I live in Berlin now"

RAN: python3 -m cairn.cli export --db $DB --out .../export
OUTPUT: ok: exported 2 pages to .../export
        .../export/people/caroline.md
        .../export/projects/billing-v2.md
```

### Packaging

```
RAN: /opt/homebrew/bin/python3.12 -m venv /tmp/cairn-venv2 && pip install . && cairn init --db /tmp/pkgtest.db
OUTPUT: ok: initialised brain id=1 workspace='default' at /tmp/pkgtest.db
        cairn page --db /tmp/pkgtest.db people/x -> error: page 'people/x' not found (exit 1)
```

### MCP degradation (mcp not installed on this machine)

```
RAN: python3 -m cairn.mcp_server
OUTPUT: error: The `mcp` package is not installed. Install it with: pip install "cairn[mcp]"  (or: pip install mcp)
        exit code 1
```

## Caveats / unverified

- UNVERIFIED: the MCP server was not exercised over a live stdio MCP session — the `mcp` package is not installed here, so only the graceful-degradation path and the tool bodies were verified. Installing `pip install ".[mcp]"` and connecting a client is the remaining check.
- The system `python3` is 3.9.6, so `pip install .` refuses it by design (`requires-python = ">=3.10"`); the test suite runs under 3.9 via `sys.path` insertion in the test files. Packaging was verified under Homebrew Python 3.12.
- The live smoke test and the end-to-end run above depend on the local endpoints being up; they skip/fail loudly when they are not.
