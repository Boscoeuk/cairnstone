"""Phase 10 CLI: the `cairnstone` console script.

Subcommands: init, ingest, compile, search, brief, page, history, export.

`init`, `ingest`, `search`, `page`, `history` and `export` need no inference
model. `compile` and `brief` call the local endpoint configured by CAIRN_BASE_URL
(default http://127.0.0.1:8460/v1) and CAIRN_MODEL (default glm-5.3-flash).
There is no cloud fallback: an unreachable endpoint exits non-zero (policy P12).

Every command prints a short machine-greppable line starting with "ok:" or
"error:" and exits 0 or non-zero accordingly.
"""

import argparse
import json
import os
import sys
import urllib.error

from . import retrieve, store
from .compile import compile_capture, dedupe, supersede_contradictions
from .llm import DEFAULT_BASE_URL, DEFAULT_MODEL, LLMClient, LLMError

DEFAULT_BRAIN = ("default", "default")  # (workspace name, brain slug)

MAX_REJECT_RATE_DEFAULT = 0.25


class CliError(Exception):
    """A command failed; the message is printed as `error: ...`."""


# ------------------------------------------------------------------ helpers

def _open_db(path):
    if not os.path.exists(path):
        raise CliError("database %r does not exist; run `cairnstone init --db %s` first"
                       % (path, path))
    return store.init_db(path)


def _brain_id(conn):
    ws, slug = DEFAULT_BRAIN
    row = conn.execute(
        "SELECT b.id FROM brains b JOIN workspaces w ON w.id = b.workspace_id"
        " WHERE w.name = ? AND b.slug = ?", (ws, slug)).fetchone()
    if row is None:
        raise CliError("no default brain in this database; run `cairnstone init` first")
    return row["id"]


def _env(suffix, default=None):
    """Read a Cairnstone setting, preferring CAIRNSTONE_* over the legacy CAIRN_*.

    The project was renamed before release but the environment prefix was left behind,
    so both spellings must work: new installs document CAIRNSTONE_*, older shells and
    profiles still export CAIRN_*.
    """
    for prefix in ("CAIRNSTONE_", "CAIRN_"):
        value = os.environ.get(prefix + suffix)
        if value:
            return value
    return default


def _client():
    base_url = _env("BASE_URL", DEFAULT_BASE_URL)
    model = _env("MODEL", DEFAULT_MODEL)
    return LLMClient(base_url=base_url, model=model)


def _require_endpoint(client):
    """Fail loudly before compiling if the local endpoint is unreachable (P12).

    The extractor converts any chat failure into a generic ExtractError, so
    without this check an unreachable endpoint would look like bad model output.
    """
    import urllib.request
    req = urllib.request.Request(client.base_url + "/models", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                raise CliError("local endpoint %s returned HTTP %d; no cloud "
                               "fallback (policy P12)" % (client.base_url,
                                                          resp.status))
    except CliError:
        raise
    except Exception as exc:
        raise CliError("local endpoint %s unreachable (%s); no cloud fallback "
                       "(policy P12)" % (client.base_url, exc)) from exc


# ----------------------------------------------------------------- commands

def cmd_init(args):
    if os.path.exists(args.db):
        raise CliError("database %r already exists" % args.db)
    conn = store.init_db(args.db)
    ws_id = store.create_workspace(conn, DEFAULT_BRAIN[0])
    brain_id = store.create_brain(conn, ws_id, DEFAULT_BRAIN[0], DEFAULT_BRAIN[1])
    print("ok: initialised brain id=%d workspace=%r at %s"
          % (brain_id, DEFAULT_BRAIN[0], args.db))
    return 0


def cmd_ingest(args):
    if args.kind not in ("note", "chat", "document"):
        raise CliError("kind must be note, chat or document (got %r)" % args.kind)
    conn = _open_db(args.db)
    brain_id = _brain_id(conn)
    with open(args.file, "r", encoding="utf-8") as fh:
        content = fh.read()
    capture_id = store.add_capture(conn, brain_id, args.kind, content, args.source)
    print("ok: capture id=%d kind=%s source=%r bytes=%d"
          % (capture_id, args.kind, args.source, len(content)))
    return 0


def cmd_compile(args):
    conn = _open_db(args.db)
    brain_id = _brain_id(conn)
    capture_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM captures WHERE brain_id = ? ORDER BY id", (brain_id,))]
    if not capture_ids:
        raise CliError("no captures to compile; run `cairnstone ingest` first")
    client = _client()
    _require_endpoint(client)
    accepted = 0
    rejected = 0
    failed = []
    # Policy P2: a run rejecting more than max_reject_rate is an extractor
    # failure; stop rather than writing a thin brain.
    for cid in capture_ids:
        result = compile_capture(conn, brain_id, cid, client)
        if not result["ok"]:
            failed.append(cid)
            continue
        accepted += result["accepted"]
        rejected += len(result["rejected"])
        rate = rejected / (accepted + rejected) if (accepted + rejected) else 0.0
        if rate > args.max_reject_rate:
            raise CliError(
                "reject rate %.2f exceeds max_reject_rate %.2f after capture %d; "
                "stopped without dedupe/supersede (policy P2)"
                % (rate, args.max_reject_rate, cid))
    if accepted + rejected == 0:
        raise CliError("extraction produced no facts for any capture "
                       "(failed captures: %s)" % failed)
    duplicates = dedupe(conn, brain_id)
    superseded = supersede_contradictions(conn, brain_id)
    print("ok: compiled captures=%d accepted=%d rejected=%d duplicates_linked=%d "
          "superseded=%d failed_captures=%s"
          % (len(capture_ids), accepted, rejected, duplicates, superseded, failed))
    return 0


def cmd_search(args):
    conn = _open_db(args.db)
    brain_id = _brain_id(conn)
    try:
        results = retrieve.search(conn, brain_id, args.query, k=args.limit)
    except (urllib.error.URLError, OSError) as exc:
        # The embedding endpoint is local-only (P12); when it is down, degrade
        # to FTS over pages rather than reaching for any other model.
        print("warning: embedding endpoint unreachable (%s); FTS-only search"
              % exc, file=sys.stderr)
        results = [{"kind": "page", "id": r["id"], "score": -r["rank"],
                    "text": r["title"], "page_id": r["id"], "status": "page"}
                   for r in store.search_pages(conn, args.query, limit=args.limit)]
    if not results:
        print("error: no results for %r" % args.query)
        return 1
    for r in results:
        print("ok: %s id=%s score=%.4f %s" % (r["kind"], r["id"], r["score"],
                                              r["text"].replace("\n", " ")))
    return 0


def cmd_brief(args):
    conn = _open_db(args.db)
    brain_id = _brain_id(conn)
    stable, volatile, facts = retrieve.build_brief(
        conn, brain_id, args.query, budget_tokens=args.budget)
    client = _client()
    _require_endpoint(client)
    answer = client.chat(
        [{"role": "system", "content": stable},
         {"role": "user", "content": volatile +
          "\n\nReply with a short answer only, citing nothing: the citation "
          "lines below carry the evidence. If no record answers the question, "
          "reply exactly: not recorded."}],
        max_tokens=256)
    print("answer: %s" % answer.strip())
    print("brief:")
    print(stable)
    print(volatile)
    print("citations:")
    for c in retrieve.render_citations(conn, [f["id"] for f in facts]):
        print("- [capture %s span %d:%d] %s -- \"%s\""
              % (c["source_ref"], c["span"][0], c["span"][1], c["text"], c["quote"]))
    print("ok: brief facts=%d" % len(facts))
    return 0


def cmd_page(args):
    conn = _open_db(args.db)
    brain_id = _brain_id(conn)
    try:
        result = store.get_page(conn, args.path, brain_id=brain_id)
    except store.NotFoundError as exc:
        raise CliError(str(exc)) from exc
    page = result["page"]
    print("ok: page id=%d path=%s bucket=%s" % (page["id"], page["path"],
                                                page["bucket"]))
    print(result["body_md"])
    facts = store.facts_for_page(conn, page["id"], status="active")
    for f in facts:
        print("- %s [capture %d span %d:%d]"
              % (f["text"], f["capture_id"], f["span_start"], f["span_end"]))
    return 0


def cmd_history(args):
    conn = _open_db(args.db)
    row = conn.execute(
        "SELECT f.id, f.text, f.status, f.superseded_by, f.duplicate_of,"
        " f.capture_id, f.span_start, f.span_end, f.quote, p.path"
        " FROM facts f JOIN pages p ON p.id = f.page_id WHERE f.id = ?",
        (args.fact_id,)).fetchone()
    if row is None:
        raise CliError("fact %d not found" % args.fact_id)
    print("ok: fact id=%d status=%s page=%s" % (row["id"], row["status"],
                                                row["path"]))
    print("text: %s" % row["text"])
    print("citation: capture %d span %d:%d" % (row["capture_id"], row["span_start"],
                                               row["span_end"]))
    print("quote: \"%s\"" % row["quote"])
    if row["superseded_by"] is not None:
        print("superseded_by: fact %d" % row["superseded_by"])
    if row["duplicate_of"] is not None:
        print("duplicate_of: fact %d" % row["duplicate_of"])
    events = conn.execute(
        "SELECT kind, created_at, payload_json FROM change_events"
        " WHERE subject_id = ? ORDER BY id", (args.fact_id,)).fetchall()
    for e in events:
        print("event: %s %s %s" % (e["created_at"], e["kind"], e["payload_json"]))
    return 0


def cmd_export(args):
    conn = _open_db(args.db)
    brain_id = _brain_id(conn)
    out_dir = args.out or os.path.join(os.path.dirname(args.db) or ".", "export")
    written = store.export_markdown(conn, brain_id, out_dir)
    if not written:
        raise CliError("no pages to export")
    print("ok: exported %d pages to %s" % (len(written), out_dir))
    for path in written:
        print(path)
    return 0


# ------------------------------------------------------------------ parser

def build_parser():
    parser = argparse.ArgumentParser(
        prog="cairnstone", description="Local-first memory compiler for AI agents.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a new store database")
    p.add_argument("--db", required=True)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("ingest", help="add a capture from a file")
    p.add_argument("--db", required=True)
    p.add_argument("--kind", required=True, help="note | chat | document")
    p.add_argument("--source", required=True, help="source label for the capture")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("compile", help="compile captures into cited facts (local model)")
    p.add_argument("--db", required=True)
    p.add_argument("--max-reject-rate", type=float, default=MAX_REJECT_RATE_DEFAULT)
    p.set_defaults(func=cmd_compile)

    p = sub.add_parser("search", help="hybrid search over facts and pages")
    p.add_argument("--db", required=True)
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("brief", help="answer a question from a cited brief (local model)")
    p.add_argument("--db", required=True)
    p.add_argument("query")
    p.add_argument("--budget", type=int, default=4000)
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("page", help="show a page and its active facts")
    p.add_argument("--db", required=True)
    p.add_argument("path")
    p.set_defaults(func=cmd_page)

    p = sub.add_parser("history", help="show a fact and its change events")
    p.add_argument("--db", required=True)
    p.add_argument("fact_id", type=int)
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("export", help="export pages as Markdown files")
    p.add_argument("--db", required=True)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_export)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (CliError, store.StoreError) as exc:
        print("error: %s" % exc)
        return 1
    except LLMError as exc:
        print("error: local model endpoint unreachable or failed (%s); "
              "there is no cloud fallback (policy P12)" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
