import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cairn import store  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    c = store.init_db(str(tmp_path / "test.db"))
    ws = store.create_workspace(c, "ws")
    brain = store.create_brain(c, ws, "brain", "brain")
    yield c, brain
    c.close()


def _capture(db, content="Alice leads the Atlas project. She started in 2024."):
    c, brain = db
    return store.add_capture(c, brain, "chat", content, "chat:1")


def test_round_trip_capture_page_version_fact(db):
    c, brain = db
    cap = _capture(db)
    page = store.create_page(c, brain, "people/alice", "people", "Alice",
                             "Alice leads Atlas.")
    version = store.get_page(c, "people/alice")["page"]["current_version_id"]
    fact = store.add_fact(c, page, version, "Alice leads the Atlas project.",
                          cap, 0, 30)
    got = store.get_page(c, "people/alice")
    assert got["page"]["id"] == page
    assert got["body_md"] == "Alice leads Atlas."
    row = c.execute("SELECT * FROM facts WHERE id = ?", (fact,)).fetchone()
    assert row["capture_id"] == cap
    assert row["span_start"] == 0 and row["span_end"] == 30
    assert row["status"] == "active"


def test_fact_without_capture_rejected(db):
    c, brain = db
    page = store.create_page(c, brain, "p", "misc", "P")
    version = store.get_page(c, "p")["page"]["current_version_id"]
    with pytest.raises(store.CitationError):
        store.add_fact(c, page, version, "text", 9999, 0, 5)
    with pytest.raises(store.CitationError):
        store.add_fact(c, page, version, "text", _capture(db), 5, 5)


def test_delete_cited_capture_refused(db):
    c, brain = db
    cap = _capture(db)
    page = store.create_page(c, brain, "p", "misc", "P")
    version = store.get_page(c, "p")["page"]["current_version_id"]
    store.add_fact(c, page, version, "text", cap, 0, 10)
    with pytest.raises(store.CitedError):
        store.delete_capture(c, cap)
    # uncited capture deletes fine
    other = store.add_capture(c, brain, "chat", "other", "chat:2")
    store.delete_capture(c, other)


def test_supersede_keeps_history(db):
    c, brain = db
    cap = _capture(db)
    page = store.create_page(c, brain, "p", "misc", "P")
    version = store.get_page(c, "p")["page"]["current_version_id"]
    f1 = store.add_fact(c, page, version, "old", cap, 0, 10)
    f2 = store.add_fact(c, page, version, "new", cap, 10, 20)
    store.supersede_fact(c, f1, f2)
    statuses = {r["id"]: r["status"] for r in
                c.execute("SELECT id, status FROM facts").fetchall()}
    assert statuses[f1] == "superseded"
    assert statuses[f2] == "active"
    assert c.execute("SELECT COUNT(*) c FROM facts").fetchone()["c"] == 2


def test_fts_finds_page(db):
    c, brain = db
    store.create_page(c, brain, "projects/atlas", "projects", "Atlas",
                      "Atlas is a distributed cache.")
    store.create_page(c, brain, "people/bob", "people", "Bob", "Bob likes tea.")
    hits = store.search_pages(c, "cache")
    assert [h["path"] for h in hits] == ["projects/atlas"]
    assert len(store.search_pages(c, "tea")) == 1


def test_page_versions_chain(db):
    c, brain = db
    page = store.create_page(c, brain, "p", "misc", "P", "v1")
    v1 = store.get_page(c, "p")["page"]["current_version_id"]
    v2 = store.add_page_version(c, page, "v2")
    v3 = store.add_page_version(c, page, "v3")
    assert store.get_page(c, "p")["body_md"] == "v3"
    chain = [r["supersedes_version_id"] for r in c.execute(
        "SELECT supersedes_version_id FROM page_versions WHERE id IN (?, ?)",
        (v2, v3)).fetchall()]
    assert chain == [v1, v2]


def test_export_writes_one_file_per_page(db, tmp_path):
    c, brain = db
    store.create_page(c, brain, "a", "misc", "A", "body a")
    store.create_page(c, brain, "nested/b", "misc", "B", "body b")
    out = tmp_path / "export"
    written = store.export_markdown(c, brain, str(out))
    assert len(written) == 2
    assert os.path.exists(out / "a.md")
    assert os.path.exists(out / "nested" / "b.md")
    assert "body a" in (out / "a.md").read_text()


def test_capture_sha256_immutable(db):
    cap = _capture(db, "hello")
    c, _ = db
    row = store.get_capture(c, cap)
    assert row["sha256"] == hashlib.sha256(b"hello").hexdigest()


# ---- added on the maintainer's independent review: the supersede link, citation evidence, and
# ---- version/page integrity were not covered by the worker's own tests.

def test_supersede_records_replacement_and_event(db):
    c, brain = db
    cap = _capture(db)
    page = store.create_page(c, brain, "p", "misc", "P")
    version = store.get_page(c, "p")["page"]["current_version_id"]
    f1 = store.add_fact(c, page, version, "ships Mar 31", cap, 0, 10)
    f2 = store.add_fact(c, page, version, "ships Apr 30", cap, 10, 20)
    store.supersede_fact(c, f1, f2)
    row = c.execute("SELECT superseded_by FROM facts WHERE id = ?", (f1,)).fetchone()
    assert row["superseded_by"] == f2
    events = c.execute(
        "SELECT * FROM change_events WHERE kind = 'fact.superseded'").fetchall()
    assert len(events) == 1 and events[0]["subject_id"] == f1


def test_supersede_self_rejected(db):
    c, brain = db
    cap = _capture(db)
    page = store.create_page(c, brain, "p", "misc", "P")
    version = store.get_page(c, "p")["page"]["current_version_id"]
    f1 = store.add_fact(c, page, version, "x", cap, 0, 10)
    with pytest.raises(store.StoreError):
        store.supersede_fact(c, f1, f1)


def test_fact_requires_version_of_same_page(db):
    c, brain = db
    cap = _capture(db)
    page_a = store.create_page(c, brain, "a", "misc", "A")
    page_b = store.create_page(c, brain, "b", "misc", "B")
    version_b = store.get_page(c, "b")["page"]["current_version_id"]
    with pytest.raises(store.CitationError):
        store.add_fact(c, page_a, version_b, "text", cap, 0, 10)


def test_whitespace_span_rejected(db):
    c, brain = db
    cap = store.add_capture(c, brain, "chat", "abc    def", "chat:1")
    page = store.create_page(c, brain, "p", "misc", "P")
    version = store.get_page(c, "p")["page"]["current_version_id"]
    with pytest.raises(store.CitationError):
        store.add_fact(c, page, version, "text", cap, 3, 7)


def test_quote_is_captured_from_source(db):
    c, brain = db
    content = "Lina Haas owns Billing v2 since Mar 12."
    cap = store.add_capture(c, brain, "chat", content, "chat:1")
    page = store.create_page(c, brain, "p", "misc", "P")
    version = store.get_page(c, "p")["page"]["current_version_id"]
    start = content.index("Lina Haas owns Billing v2")
    fid = store.add_fact(c, page, version, "Lina owns Billing v2", cap, start, start + 25)
    row = c.execute("SELECT quote FROM facts WHERE id = ?", (fid,)).fetchone()
    assert row["quote"] == content[start:start + 25]


def test_export_includes_quote(db, tmp_path):
    c, brain = db
    content = "Atlas ships in April."
    cap = store.add_capture(c, brain, "chat", content, "chat:1")
    page = store.create_page(c, brain, "projects/atlas", "projects", "Atlas")
    version = store.get_page(c, "projects/atlas")["page"]["current_version_id"]
    store.add_fact(c, page, version, "Atlas ships April", cap, 0, len(content))
    out = tmp_path / "export"
    store.export_markdown(c, brain, str(out))
    text = (out / "projects" / "atlas.md").read_text()
    assert "quote: \"Atlas ships in April.\"" in text


def test_facts_for_page_filters_status(db):
    c, brain = db
    cap = _capture(db)
    page = store.create_page(c, brain, "p", "misc", "P")
    version = store.get_page(c, "p")["page"]["current_version_id"]
    f1 = store.add_fact(c, page, version, "old", cap, 0, 10)
    store.add_fact(c, page, version, "new", cap, 10, 20)
    store.supersede_fact(c, f1, f1 + 1)
    assert [f["text"] for f in store.facts_for_page(c, page, "active")] == ["new"]
    assert [f["text"] for f in store.facts_for_page(c, page, "superseded")] == ["old"]
