# Phase 10 — verified, with one real defect found and fixed (the maintainer)

## What I verified myself

**81 tests pass** (69 pre-existing + 12 new). `LICENSE` is the full Apache-2.0 text (202 lines).
`pyproject.toml` declares `cairn`, `requires-python >=3.10`, and the `cairn` console script.
`src/cairn/cli.py` (317 lines) and `src/cairn/mcp_server.py` (232 lines) exist; README is 111 lines.

**CLI end to end against a fresh database**, run by me, not reported by the worker:

```
init            -> ok: initialised brain id=1 ... rc=0
ingest x3       -> ok: capture id=1/2/3 ... rc=0
compile         -> ok: compiled captures=3 accepted=3 rejected=1 ... rc=0
search Berlin   -> ok: fact id=1 score=0.7786 Caroline lives in Berlin ... rc=0
brief           -> answer: Caroline lives in Berlin.
                   citations: [capture n1 span 10:45] ... "I live in Berlin now and I love it."
page            -> facts with capture ids and spans
export          -> ok: exported 2 pages (people/caroline.md, people/melanie.md)
```

The exported Markdown carries claim → capture → span → verbatim quote, which is the product's
central promise.

## Defect: the MCP server did not work with a current `mcp` install

Phase 10 reported the MCP server as unverified because `mcp` wasn't installed. I installed it in a
Python 3.12 venv and ran a **real stdio MCP client session**. It failed:

```
error: The `mcp` package is not installed. Install it with: pip install "cairn[mcp]"
```

But `mcp` *was* installed. Cause: `pip install mcp` now yields mcp 2.x, where `FastMCP` was renamed
to `MCPServer` (`mcp.server.mcpserver`). `mcp/server/fastmcp.py` still exists as a shim that raises
`ModuleNotFoundError` — an `ImportError` subclass — so the server's `except ImportError` reported
"not installed" while the package was present and healthy. Anyone following the README would have
hit a misleading error and concluded cairn's MCP support was broken.

**Fix**: `_mcp_server_class()` resolves the server class via `importlib` across
`mcp.server.mcpserver.MCPServer` (2.x) and `mcp.server.fastmcp.FastMCP` (1.x), and reports a
version-accurate error when neither exists. Both classes accept `(name, instructions=...)`, `.tool()`
and `.run(transport="stdio")`, so the tool bodies are unchanged.

**Verified live after the fix**, over a real stdio session:

```
TOOLS: ['brief', 'capture', 'compile', 'export_markdown', 'fact_history', 'get_page', 'search']
SEARCH: fact id=1 score=0.7786 Caroline lives in Berlin
BRIEF:  answer: Caroline lives in Berlin. + citations with capture/span/quote
PAGE:   # Caroline (people/caroline) ## Facts - Caroline lives in Berlin [capture 1 span 10:45]
```

All seven tools are reachable and return citation-bearing text.

## Still not done

- The MCP server was verified against **mcp 2.x**; the 1.x path is written but unexercised.
- Packaging warns that `project.license` as a TOML table is deprecated (use an SPDX string). Cosmetic,
  but it will break on setuptools>=77 defaults in 2027.
- Cairn is not yet registered in any Hermes profile, so nothing uses it as memory yet.
