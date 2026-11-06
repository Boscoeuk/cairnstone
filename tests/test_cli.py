"""Phase 10 CLI tests: offline coverage for every model-free command, a
no-cloud-fallback proof for compile/brief, and one live smoke test gated on
the local endpoint being reachable."""

import os
import sqlite3
import sys
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cairnstone import cli, store  # noqa: E402

LIVE_URL = "http://127.0.0.1:8460/v1"


def _live_endpoint_up():
    try:
        with urllib.request.urlopen(LIVE_URL + "/models", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "cli.db")
    assert cli.main(["init", "--db", path]) == 0
    return path


NOTE = "Caroline: I started hormones in March and I live in Berlin.\n"


def _ingest(db, tmp_path, name="note.txt", text=NOTE, kind="note",
            source="test"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    assert cli.main(["ingest", "--db", db, "--kind", kind,
                     "--source", source, "--file", str(path)]) == 0


# ------------------------------------------------------------------ init

def test_init_creates_db_and_is_idempotent_guarded(tmp_path):
    path = str(tmp_path / "a.db")
    assert cli.main(["init", "--db", path]) == 0
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM brains").fetchone()[0] == 1
    conn.close()
    # Second init must fail, not clobber.
    assert cli.main(["init", "--db", path]) == 1


# ---------------------------------------------------------------- ingest

def test_ingest_stores_hashed_capture(db, tmp_path):
    _ingest(db, tmp_path)
    conn = store.init_db(db)
    row = conn.execute("SELECT kind, source_ref, sha256, content FROM captures") \
        .fetchone()
    assert row["kind"] == "note"
    assert row["source_ref"] == "test"
    assert len(row["sha256"]) == 64
    assert row["content"] == NOTE


def test_ingest_rejects_unknown_kind(db, tmp_path, capsys):
    path = tmp_path / "x.txt"
    path.write_text("hello", encoding="utf-8")
    assert cli.main(["ingest", "--db", db, "--kind", "tweet",
                     "--source", "s", "--file", str(path)]) == 1
    assert "error:" in capsys.readouterr().out


# ------------------------------------------------- compile/brief: no cloud

def test_compile_fails_loudly_when_endpoint_unreachable(db, tmp_path, monkeypatch,
                                                        capsys):
    _ingest(db, tmp_path)
    monkeypatch.setenv("CAIRN_BASE_URL", "http://127.0.0.1:1/v1")
    assert cli.main(["compile", "--db", db]) == 1
    out = capsys.readouterr().out
    assert "error:" in out
    assert "no cloud fallback" in out


def test_brief_fails_loudly_when_endpoint_unreachable(db, tmp_path, monkeypatch,
                                                      capsys):
    _ingest(db, tmp_path)
    monkeypatch.setenv("CAIRN_BASE_URL", "http://127.0.0.1:1/v1")
    assert cli.main(["brief", "--db", db, "where does Caroline live"]) == 1
    assert "error:" in capsys.readouterr().out


# ---------------------------------------------------------------- search

def test_search_degrades_to_fts_when_embeddings_down(db, tmp_path, monkeypatch,
                                                     capsys):
    _ingest(db, tmp_path)
    from cairnstone import retrieve
    monkeypatch.setattr(retrieve, "cached_embeddings",
                        lambda *a, **k: (_ for _ in ()).throw(
                            urllib.error.URLError("connection refused")))
    assert cli.main(["search", "--db", db, "Caroline", "--limit", "3"]) == 1
    # No pages exist yet (nothing compiled), so FTS finds nothing -> exit 1.
    assert "error:" in capsys.readouterr().out


# ------------------------------------------------------------- page/history

def _seed_page_with_fact(db):
    conn = store.init_db(db)
    brain = conn.execute(
        "SELECT id FROM brains WHERE slug = 'default'").fetchone()["id"]
    cid = store.add_capture(conn, brain, "note", NOTE, "seed")
    page_id = store.create_page(conn, brain, "people/caroline", "people",
                                "Caroline", "Seed body.")
    version_id = conn.execute(
        "SELECT current_version_id FROM pages WHERE id = ?", (page_id,)) \
        .fetchone()["current_version_id"]
    fact_id = store.add_fact(conn, page_id, version_id,
                             "Caroline lives in Berlin", cid, 40, 58)
    conn.close()
    return fact_id


def test_page_prints_body_and_facts(db, capsys):
    fact_id = _seed_page_with_fact(db)
    assert cli.main(["page", "--db", db, "people/caroline"]) == 0
    out = capsys.readouterr().out
    assert "ok: page" in out
    assert "Seed body." in out
    assert "Caroline lives in Berlin" in out


def test_page_missing_path_exits_nonzero(db, capsys):
    assert cli.main(["page", "--db", db, "people/nobody"]) == 1
    assert "error:" in capsys.readouterr().out


def test_history_shows_citation_and_events(db, capsys):
    fact_id = _seed_page_with_fact(db)
    assert cli.main(["history", "--db", db, str(fact_id)]) == 0
    out = capsys.readouterr().out
    assert "ok: fact id=%d" % fact_id in out
    assert "citation: capture" in out
    assert "quote:" in out
    assert "event: " in out


def test_history_missing_fact_exits_nonzero(db, capsys):
    assert cli.main(["history", "--db", db, "999"]) == 1
    assert "error:" in capsys.readouterr().out


# ---------------------------------------------------------------- export

def test_export_writes_markdown_files(db, tmp_path, capsys):
    _seed_page_with_fact(db)
    out_dir = str(tmp_path / "md")
    assert cli.main(["export", "--db", db, "--out", out_dir]) == 0
    written = os.path.join(out_dir, "people", "caroline.md")
    assert os.path.exists(written)
    with open(written, encoding="utf-8") as fh:
        body = fh.read()
    assert "# Caroline" in body
    assert "capture" in body  # citation line present
    assert "ok: exported" in capsys.readouterr().out


# ------------------------------------------------------------- live smoke

@pytest.mark.skipif(not _live_endpoint_up(),
                    reason="local model endpoint %s not reachable" % LIVE_URL)
def test_live_smoke_end_to_end(db, tmp_path, capsys):
    """Full pipeline against the real local endpoint. Skipped offline."""
    _ingest(db, tmp_path, source="smoke")
    assert cli.main(["compile", "--db", db]) == 0
    assert "ok: compiled" in capsys.readouterr().out
    assert cli.main(["search", "--db", db, "Caroline", "--limit", "3"]) == 0
    assert "ok:" in capsys.readouterr().out
    assert cli.main(["brief", "--db", db, "Where does Caroline live?"]) == 0
    out = capsys.readouterr().out
    assert "answer:" in out
    assert "citations:" in out
    assert cli.main(["export", "--db", db, "--out", str(tmp_path / "md")]) == 0
    assert "ok: exported" in capsys.readouterr().out


def test_cairnstone_env_prefix_wins(monkeypatch):
    """CAIRNSTONE_* is the documented prefix and must beat the legacy CAIRN_*."""
    monkeypatch.setenv("CAIRNSTONE_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("CAIRN_BASE_URL", "http://127.0.0.1:1111/v1")
    monkeypatch.setenv("CAIRNSTONE_MODEL", "model-new")
    monkeypatch.setenv("CAIRN_MODEL", "model-old")
    client = cli._client()
    assert client.base_url == "http://127.0.0.1:9999/v1"
    assert client.model == "model-new"


def test_legacy_cairn_env_still_honoured(monkeypatch):
    """A shell that predates the rename must keep working."""
    monkeypatch.delenv("CAIRNSTONE_BASE_URL", raising=False)
    monkeypatch.delenv("CAIRNSTONE_MODEL", raising=False)
    monkeypatch.setenv("CAIRN_BASE_URL", "http://127.0.0.1:1111/v1")
    monkeypatch.setenv("CAIRN_MODEL", "model-old")
    client = cli._client()
    assert client.base_url == "http://127.0.0.1:1111/v1"
    assert client.model == "model-old"
