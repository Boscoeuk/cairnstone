"""Phase 10 MCP server: exposes cairnstone over stdio using the `mcp` package.

Tools: capture, compile, search, brief, get_page, fact_history, export_markdown.

Run with: python -m cairnstone.mcp_server  (or `cairnstone-mcp`, if installed)

If the `mcp` package is not installed, importing this module raises a clear
error instead of a confusing traceback; use `install_cairn_mcp_hint()`-style
message via `require_mcp()`. Install the extra with: pip install "cairnstone[mcp]".

The server talks to the same local-only stack as the CLI (policy P12): the
compile and brief tools call the local model endpoint configured by
CAIRN_BASE_URL / CAIRN_MODEL; there is no cloud fallback.
"""

import argparse
import importlib
import os
import sys

from . import retrieve, store
from .llm import DEFAULT_BASE_URL, DEFAULT_MODEL, LLMClient

MCP_INSTALL_HINT = (
    "The `mcp` package is not installed. Install it with: "
    'pip install "cairnstone[mcp]"  (or: pip install mcp)'
)

DEFAULT_DB = os.environ.get("CAIRNSTONE_DB") or os.environ.get("CAIRN_DB") or "cairnstone.db"
DEFAULT_BRAIN = ("default", "default")


def _mcp_server_class():
    """Return the MCP server class for the installed SDK version.

    mcp 2.x renamed FastMCP to MCPServer (`mcp.server.mcpserver`); mcp 1.x exposes
    `mcp.server.fastmcp.FastMCP`. Both accept (name, instructions=...) and provide
    `.tool()` and `.run(transport="stdio")`, so the tool bodies below are shared.

    Importing `mcp.server.fastmcp` on mcp 2.x raises ModuleNotFoundError, which is an
    ImportError subclass — so a plain try/except around it reported "mcp not installed"
    when mcp *was* installed, which is exactly the misleading failure this avoids.
    """
    try:
        import mcp  # noqa: F401
    except ImportError:
        print("error: %s" % MCP_INSTALL_HINT, file=sys.stderr)
        sys.exit(1)
    for module_path, attr in (("mcp.server.mcpserver", "MCPServer"),
                              ("mcp.server.fastmcp", "FastMCP")):
        try:
            module = importlib.import_module(module_path)
        except ImportError:
            continue
        server_cls = getattr(module, attr, None)
        if server_cls is not None:
            return server_cls
    print("error: the installed `mcp` package exposes neither MCPServer nor "
          "FastMCP; use mcp>=2 or mcp<2", file=sys.stderr)
    sys.exit(1)


def require_mcp():
    """Verify that `mcp` is installed and exposes a usable server class."""
    return _mcp_server_class()


def _brain_id(conn):
    ws, slug = DEFAULT_BRAIN
    row = conn.execute(
        "SELECT b.id FROM brains b JOIN workspaces w ON w.id = b.workspace_id"
        " WHERE w.name = ? AND b.slug = ?", (ws, slug)).fetchone()
    if row is None:
        raise ValueError("no default brain in %r; run `cairnstone init --db %s` first"
                         % (db_path(), DEFAULT_DB))
    return row["id"]


def db_path():
    return (os.environ.get("CAIRNSTONE_DB") or os.environ.get("CAIRN_DB")
            or DEFAULT_DB)


def _client():
    base_url = (os.environ.get("CAIRNSTONE_BASE_URL") or os.environ.get("CAIRN_BASE_URL")
                or DEFAULT_BASE_URL)
    model = (os.environ.get("CAIRNSTONE_MODEL") or os.environ.get("CAIRN_MODEL")
             or DEFAULT_MODEL)
    return LLMClient(base_url=base_url, model=model)


# ------------------------------------------------------------- tool bodies
# Each returns plain text; MCP tools surface these strings to the client.

def tool_capture(kind, source, text):
    """Add a capture (note | chat | document) to the default brain."""
    if kind not in ("note", "chat", "document"):
        return "error: kind must be note, chat or document (got %r)" % kind
    conn = store.init_db(db_path())
    capture_id = store.add_capture(conn, _brain_id(conn), kind, text, source)
    return "ok: capture id=%d kind=%s source=%r bytes=%d" % (
        capture_id, kind, source, len(text))


def tool_compile():
    """Compile all captures into cited facts using the local model endpoint."""
    from .compile import compile_all
    conn = store.init_db(db_path())
    brain_id = _brain_id(conn)
    capture_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM captures WHERE brain_id = ? ORDER BY id", (brain_id,))]
    if not capture_ids:
        return "error: no captures to compile"
    summary = compile_all(conn, brain_id, capture_ids, _client())
    return "ok: compiled captures=%d accepted=%d rejected=%d duplicates_linked=%d " \
           "superseded=%d failed_captures=%s" % (
               summary["captures"], summary["facts_accepted"],
               len(summary["facts_rejected"]), summary["duplicates_linked"],
               summary["superseded"], summary["failed_captures"])


def tool_search(query, limit=10):
    """Hybrid (FTS + embedding) search over facts and pages."""
    conn = store.init_db(db_path())
    results = retrieve.search(conn, _brain_id(conn), query, k=limit)
    if not results:
        return "no results for %r" % query
    return "\n".join(
        "%s id=%s score=%.4f %s" % (r["kind"], r["id"], r["score"],
                                    r["text"].replace("\n", " "))
        for r in results)


def tool_brief(question, budget_tokens=4000):
    """Answer a question from a citation-bearing brief (local model endpoint)."""
    conn = store.init_db(db_path())
    brain_id = _brain_id(conn)
    stable, volatile, facts = retrieve.build_brief(
        conn, brain_id, question, budget_tokens=budget_tokens)
    answer = _client().chat(
        [{"role": "system", "content": stable},
         {"role": "user", "content": volatile}],
        max_tokens=256)
    lines = ["answer: %s" % answer.strip(), "citations:"]
    for c in retrieve.render_citations(conn, [f["id"] for f in facts]):
        lines.append("- [capture %s span %d:%d] %s -- \"%s\""
                     % (c["source_ref"], c["span"][0], c["span"][1],
                        c["text"], c["quote"]))
    return "\n".join(lines)


def tool_get_page(path):
    """Return a page's current body and active facts."""
    conn = store.init_db(db_path())
    result = store.get_page(conn, path, brain_id=_brain_id(conn))
    page = result["page"]
    facts = store.facts_for_page(conn, page["id"], status="active")
    lines = ["# %s (%s)" % (page["title"], page["path"]), result["body_md"],
             "## Facts"]
    lines += ["- %s [capture %d span %d:%d]"
              % (f["text"], f["capture_id"], f["span_start"], f["span_end"])
              for f in facts]
    return "\n".join(lines)


def tool_fact_history(fact_id):
    """Return a fact's citation, quote, status and change events."""
    conn = store.init_db(db_path())
    row = conn.execute(
        "SELECT f.id, f.text, f.status, f.superseded_by, f.duplicate_of,"
        " f.capture_id, f.span_start, f.span_end, f.quote"
        " FROM facts f WHERE f.id = ?", (fact_id,)).fetchone()
    if row is None:
        return "error: fact %d not found" % fact_id
    lines = ["fact %d status=%s" % (row["id"], row["status"]),
             "text: %s" % row["text"],
             "citation: capture %d span %d:%d"
             % (row["capture_id"], row["span_start"], row["span_end"]),
             "quote: \"%s\"" % row["quote"]]
    if row["superseded_by"] is not None:
        lines.append("superseded_by: fact %d" % row["superseded_by"])
    if row["duplicate_of"] is not None:
        lines.append("duplicate_of: fact %d" % row["duplicate_of"])
    events = conn.execute(
        "SELECT kind, created_at, payload_json FROM change_events"
        " WHERE subject_id = ? ORDER BY id", (fact_id,)).fetchall()
    lines += ["event: %s %s %s" % (e["created_at"], e["kind"], e["payload_json"])
              for e in events]
    return "\n".join(lines)


def tool_export_markdown(out_dir=None):
    """Export every page as one Markdown file per page. Returns written paths."""
    conn = store.init_db(db_path())
    out_dir = out_dir or os.path.join(os.path.dirname(db_path()) or ".", "export")
    written = store.export_markdown(conn, _brain_id(conn), out_dir)
    if not written:
        return "error: no pages to export"
    return "ok: exported %d pages to %s\n%s" % (len(written), out_dir,
                                                "\n".join(written))


# ------------------------------------------------------------------ server

def build_server():
    """Build the MCP server object. Requires the `mcp` package."""
    server_cls = _mcp_server_class()

    mcp = server_cls("cairnstone", instructions=(
        "Cairnstone: a local-first memory compiler. Capture text, compile it into "
        "cited facts, and ask questions that are answered from citation-bearing "
        "briefs. Local endpoints only; no cloud."))

    @mcp.tool()
    def capture(kind: str, source: str, text: str) -> str:
        """Add a capture (kind: note | chat | document) with a source label."""
        return tool_capture(kind, source, text)

    @mcp.tool()
    def compile() -> str:
        """Compile all captures into cited facts (calls the local model endpoint)."""
        return tool_compile()

    @mcp.tool()
    def search(query: str, limit: int = 10) -> str:
        """Hybrid search over facts and pages."""
        return tool_search(query, limit)

    @mcp.tool()
    def brief(question: str, budget_tokens: int = 4000) -> str:
        """Answer a question from a citation-bearing brief (local model endpoint)."""
        return tool_brief(question, budget_tokens)

    @mcp.tool()
    def get_page(path: str) -> str:
        """Return a page's current body and its active cited facts."""
        return tool_get_page(path)

    @mcp.tool()
    def fact_history(fact_id: int) -> str:
        """Return a fact's citation, quote, status and change events."""
        return tool_fact_history(fact_id)

    @mcp.tool()
    def export_markdown(out_dir: str = "") -> str:
        """Export every page as one Markdown file per page."""
        return tool_export_markdown(out_dir or None)

    return mcp


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="cairnstone-mcp", description="Cairnstone MCP server (stdio).")
    parser.parse_args(argv)
    server = build_server()
    server.run()  # stdio transport is FastMCP's default


if __name__ == "__main__":
    main()
