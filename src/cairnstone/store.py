"""Cairnstone core store: SQLite-backed storage layer (Phase 1).

Stdlib sqlite3 only. Every fact carries a citation (capture id + span);
there is no uncited-fact state.
"""

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brains (
    id INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, slug)
);

CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    source_ref TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS buckets (
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    name TEXT NOT NULL,
    PRIMARY KEY (brain_id, name)
);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    path TEXT NOT NULL,
    bucket TEXT NOT NULL,
    title TEXT NOT NULL,
    current_version_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (brain_id, path)
);

CREATE TABLE IF NOT EXISTS page_versions (
    id INTEGER PRIMARY KEY,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    body_md TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    supersedes_version_id INTEGER REFERENCES page_versions(id)
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    page_version_id INTEGER NOT NULL REFERENCES page_versions(id),
    text TEXT NOT NULL,
    capture_id INTEGER NOT NULL REFERENCES captures(id),
    span_start INTEGER NOT NULL,
    span_end INTEGER NOT NULL,
    quote TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','superseded','retracted')),
    superseded_by INTEGER REFERENCES facts(id),
    duplicate_of INTEGER REFERENCES facts(id)
);

CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY,
    from_page_id INTEGER NOT NULL REFERENCES pages(id),
    to_page_id INTEGER NOT NULL REFERENCES pages(id),
    kind TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_events (
    id INTEGER PRIMARY KEY,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    kind TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_captures_brain ON captures(brain_id);
CREATE INDEX IF NOT EXISTS idx_pages_brain_path ON pages(brain_id, path);
CREATE INDEX IF NOT EXISTS idx_facts_capture ON facts(capture_id);
CREATE INDEX IF NOT EXISTS idx_facts_page ON facts(page_id);
CREATE INDEX IF NOT EXISTS idx_versions_page ON page_versions(page_id);

CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    path, title, body_md, content=''
);

CREATE TRIGGER IF NOT EXISTS pages_fts_delete BEFORE DELETE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, path, title, body_md)
    VALUES ('delete', old.id, old.path, old.title,
            (SELECT body_md FROM pages_fts WHERE rowid = old.id));
END;
"""

DEFAULT_BUCKETS = ("people", "projects", "decisions", "customers", "misc")


class StoreError(Exception):
    """Base class for store errors."""


class CitationError(StoreError):
    """A fact was submitted without a valid capture citation."""


class CitedError(StoreError):
    """A capture still cited by facts cannot be deleted."""


class NotFoundError(StoreError):
    """The requested row does not exist."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha256(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def init_db(path):
    """Open (creating if needed) a store database. Returns a sqlite3.Connection."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def create_workspace(conn, name):
    cur = conn.execute(
        "INSERT INTO workspaces(name, created_at) VALUES (?, ?)", (name, _now())
    )
    conn.commit()
    return cur.lastrowid


def create_brain(conn, workspace_id, name, slug):
    cur = conn.execute(
        "INSERT INTO brains(workspace_id, name, slug, created_at) VALUES (?, ?, ?, ?)",
        (workspace_id, name, slug, _now()),
    )
    brain_id = cur.lastrowid
    conn.executemany(
        "INSERT OR IGNORE INTO buckets(brain_id, name) VALUES (?, ?)",
        [(brain_id, b) for b in DEFAULT_BUCKETS],
    )
    conn.commit()
    return brain_id


def add_capture(conn, brain_id, kind, content, source_ref, captured_at=None):
    """Insert an immutable, hashed capture. Returns capture id."""
    cur = conn.execute(
        "INSERT INTO captures(brain_id, kind, content, sha256, captured_at, source_ref)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (brain_id, kind, content, _sha256(content), captured_at or _now(), source_ref),
    )
    capture_id = cur.lastrowid
    conn.execute(
        "INSERT INTO change_events(brain_id, kind, subject_id, created_at, payload_json)"
        " VALUES (?, 'capture.created', ?, ?, ?)",
        (brain_id, capture_id, _now(), json.dumps({"sha256": _sha256(content)})),
    )
    conn.commit()
    return capture_id


def get_capture(conn, capture_id):
    row = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
    if row is None:
        raise NotFoundError("capture %d not found" % capture_id)
    return row


def _sync_page_fts(conn, page_id, path, title, body_md):
    old = conn.execute(
        "SELECT path, title, body_md FROM pages_fts WHERE rowid = ?",
        (page_id,),
    ).fetchone()
    if old is not None:
        conn.execute(
            "INSERT INTO pages_fts(pages_fts, rowid, path, title, body_md)"
            " VALUES ('delete', ?, ?, ?, ?)",
            (page_id, old["path"], old["title"], old["body_md"]),
        )
    conn.execute(
        "INSERT INTO pages_fts(rowid, path, title, body_md) VALUES (?, ?, ?, ?)",
        (page_id, path, title, body_md),
    )


def create_page(conn, brain_id, path, bucket, title, body_md="", created_by="system"):
    """Create a page with its first version. Returns page id."""
    if bucket not in DEFAULT_BUCKETS:
        raise StoreError("unknown bucket %r" % bucket)
    cur = conn.execute(
        "INSERT INTO pages(brain_id, path, bucket, title, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (brain_id, path, bucket, title, _now(), _now()),
    )
    page_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO page_versions(page_id, body_md, created_by, created_at)"
        " VALUES (?, ?, ?, ?)",
        (page_id, body_md, created_by, _now()),
    )
    version_id = cur.lastrowid
    conn.execute(
        "UPDATE pages SET current_version_id = ? WHERE id = ?", (version_id, page_id)
    )
    conn.execute(
        "INSERT INTO change_events(brain_id, kind, subject_id, created_at, payload_json)"
        " VALUES (?, 'page.created', ?, ?, ?)",
        (brain_id, page_id, _now(), json.dumps({"path": path})),
    )
    _sync_page_fts(conn, page_id, path, title, body_md)
    conn.commit()
    return page_id


def add_page_version(conn, page_id, body_md, created_by="system"):
    """Append a new version and make it current. Returns version id."""
    row = conn.execute(
        "SELECT current_version_id FROM pages WHERE id = ?", (page_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError("page %d not found" % page_id)
    cur = conn.execute(
        "INSERT INTO page_versions(page_id, body_md, created_by, created_at,"
        " supersedes_version_id) VALUES (?, ?, ?, ?, ?)",
        (page_id, body_md, created_by, _now(), row["current_version_id"]),
    )
    version_id = cur.lastrowid
    conn.execute(
        "UPDATE pages SET current_version_id = ?, updated_at = ? WHERE id = ?",
        (version_id, _now(), page_id),
    )
    path, title = conn.execute(
        "SELECT path, title FROM pages WHERE id = ?", (page_id,)
    ).fetchone()
    _sync_page_fts(conn, page_id, path, title, body_md)
    conn.commit()
    return version_id


def add_fact(conn, page_id, page_version_id, text, capture_id, span_start, span_end,
             status="active"):
    """Insert a cited fact. Raises CitationError on a missing capture, an empty span, a span
    outside the capture, or a version that does not belong to the page.

    The cited span is copied into `quote` at write time. A fact's claim and its quote need not
    be textually identical (the claim is an extraction), but the quote is the immutable evidence
    and is what export and any citation view display.
    """
    if conn.execute("SELECT 1 FROM captures WHERE id = ?", (capture_id,)).fetchone() is None:
        raise CitationError("capture %d does not exist" % capture_id)
    if span_start is None or span_end is None or span_end <= span_start:
        raise CitationError("empty span [%r, %r)" % (span_start, span_end))
    owner = conn.execute(
        "SELECT page_id FROM page_versions WHERE id = ?", (page_version_id,)
    ).fetchone()
    if owner is None:
        raise CitationError("page version %d does not exist" % page_version_id)
    if owner["page_id"] != page_id:
        raise CitationError("page version %d belongs to page %d, not %d"
                            % (page_version_id, owner["page_id"], page_id))
    content = get_capture(conn, capture_id)["content"]
    if not (0 <= span_start < span_end <= len(content)):
        raise CitationError("span [%d, %d) out of bounds for capture %d"
                            % (span_start, span_end, capture_id))
    quote = content[span_start:span_end].strip()
    if not quote:
        raise CitationError("span [%d, %d) of capture %d is whitespace"
                            % (span_start, span_end, capture_id))
    cur = conn.execute(
        "INSERT INTO facts(page_id, page_version_id, text, capture_id, span_start,"
        " span_end, quote, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (page_id, page_version_id, text, capture_id, span_start, span_end, quote, status),
    )
    conn.commit()
    return cur.lastrowid


def supersede_fact(conn, fact_id, by_fact_id):
    """Mark a fact superseded by another, recording the replacement. History is never deleted."""
    row = conn.execute("SELECT id, status FROM facts WHERE id = ?", (fact_id,)).fetchone()
    if row is None:
        raise NotFoundError("fact %d not found" % fact_id)
    if conn.execute("SELECT 1 FROM facts WHERE id = ?", (by_fact_id,)).fetchone() is None:
        raise NotFoundError("replacement fact %d not found" % by_fact_id)
    if fact_id == by_fact_id:
        raise StoreError("a fact cannot supersede itself")
    conn.execute(
        "UPDATE facts SET status = 'superseded', superseded_by = ? WHERE id = ?",
        (by_fact_id, fact_id),
    )
    brain_id = conn.execute(
        "SELECT p.brain_id FROM pages p JOIN facts f ON f.page_id = p.id WHERE f.id = ?",
        (fact_id,),
    ).fetchone()["brain_id"]
    conn.execute(
        "INSERT INTO change_events(brain_id, kind, subject_id, created_at, payload_json)"
        " VALUES (?, 'fact.superseded', ?, ?, ?)",
        (brain_id, fact_id, _now(), json.dumps({"superseded_by": by_fact_id})),
    )
    conn.commit()


def facts_for_page(conn, page_id, status=None, include_duplicates=False):
    """Facts on a page, newest last. Optionally filtered by status.

    Duplicates are corroboration, not deletions: they stay active and carry `duplicate_of`.
    Canonical reads exclude them by default so a brief never repeats the same claim.
    """
    sql = "SELECT * FROM facts WHERE page_id = ?"
    params = [page_id]
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    if not include_duplicates:
        sql += " AND duplicate_of IS NULL"
    return conn.execute(sql + " ORDER BY id", params).fetchall()


def search_pages(conn, query, limit=10):
    """FTS5 search over pages. Returns rows ordered by rank."""
    return conn.execute(
        "SELECT p.* FROM pages_fts f JOIN pages p ON p.id = f.rowid"
        " WHERE pages_fts MATCH ? ORDER BY rank LIMIT ?",
        (query, limit),
    ).fetchall()


def get_page(conn, path, brain_id=None):
    """Fetch a page by path (optionally scoped to a brain) with its current body."""
    sql = "SELECT * FROM pages WHERE path = ?"
    params = [path]
    if brain_id is not None:
        sql += " AND brain_id = ?"
        params.append(brain_id)
    page = conn.execute(sql, params).fetchone()
    if page is None:
        raise NotFoundError("page %r not found" % path)
    body = conn.execute(
        "SELECT body_md FROM page_versions WHERE id = ?",
        (page["current_version_id"],),
    ).fetchone()
    return {"page": page, "body_md": body["body_md"] if body else ""}


def delete_capture(conn, capture_id):
    """Delete a capture; refuses while any fact cites it."""
    cited = conn.execute(
        "SELECT COUNT(*) AS n FROM facts WHERE capture_id = ?", (capture_id,)
    ).fetchone()["n"]
    if cited:
        raise CitedError("capture %d is cited by %d fact(s)" % (capture_id, cited))
    conn.execute("DELETE FROM captures WHERE id = ?", (capture_id,))
    conn.commit()


def export_markdown(conn, brain_id, out_dir):
    """Write one Markdown file per page. Returns list of written paths."""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    pages = conn.execute(
        "SELECT p.*, v.body_md FROM pages p JOIN page_versions v"
        " ON v.id = p.current_version_id WHERE p.brain_id = ? ORDER BY p.path",
        (brain_id,),
    ).fetchall()
    for page in pages:
        rel = page["path"].strip("/").replace("/", os.sep)
        out_path = os.path.join(out_dir, rel + ".md")
        os.makedirs(os.path.dirname(out_path) or out_dir, exist_ok=True)
        facts = conn.execute(
            "SELECT text, capture_id, span_start, span_end, quote FROM facts"
            " WHERE page_id = ? AND status = 'active' AND duplicate_of IS NULL"
            " ORDER BY id",
            (page["id"],),
        ).fetchall()
        lines = ["# %s" % page["title"], ""]
        if page["body_md"]:
            lines += [page["body_md"], ""]
        if facts:
            lines += ["## Facts", ""]
            for f in facts:
                lines.append("- %s" % f["text"])
                lines.append("  - source: capture %d, span %d:%d" %
                             (f["capture_id"], f["span_start"], f["span_end"]))
                lines.append("  - quote: \"%s\"" % f["quote"].replace('"', "'"))
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines).rstrip() + "\n")
        written.append(out_path)
    return written
