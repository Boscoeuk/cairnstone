"""Deterministic regression tests for the phase 15 defects (N1-N5) and the
migration backfill.

These are the defects Tes found in reports/tes-review-2.md. No model and no
network: facts are written directly with store.add_fact, then the consolidation
functions run.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cairnstone import compile as comp
from cairnstone import store
from cairnstone.compile import consolidate, dedupe


@pytest.fixture
def db(tmp_path):
    conn = store.init_db(str(tmp_path / "phase15.db"))
    ws = store.create_workspace(conn, "w")
    brain = store.create_brain(conn, ws, "b", "b")
    yield conn, brain
    conn.close()


def _capture(db, text, captured_at):
    conn, brain = db
    return store.add_capture(conn, brain, "conversation", text, "src",
                             captured_at=captured_at)


def _fact(db, text, capture_id, path="people/caroline", title="Caroline"):
    conn, brain = db
    page = conn.execute(
        "SELECT id FROM pages WHERE brain_id = ? AND path = ?",
        (brain, path)).fetchone()
    if page is None:
        page_id = store.create_page(conn, brain, path, "people", title,
                                    body_md="")
    else:
        page_id = page["id"]
    version_id = conn.execute(
        "SELECT current_version_id FROM pages WHERE id = ?",
        (page_id,)).fetchone()[0]
    content = store.get_capture(conn, capture_id)["content"]
    return store.add_fact(conn, page_id, version_id, text, capture_id,
                          0, max(1, len(content.strip())))


def _row(conn, fact_id):
    return conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()


def _active(conn, canonical_only=True):
    q = "SELECT text FROM facts WHERE status = 'active'"
    if canonical_only:
        q += " AND duplicate_of IS NULL"
    return sorted(r["text"] for r in conn.execute(q))


# ------------------------------------------------------------------ N1

def test_n1_reassertion_inside_one_batch_keeps_the_latest_truth(db):
    """Tes N1: single (May), married (Jun), single (Jul) in ONE batch must end
    with the July 'single' active and 'married' superseded.

    Before the fix, dedupe made the May fact canonical, the contradiction scan
    read only that row, and 'married' won while the July truth was hidden as a
    duplicate.
    """
    c1 = _capture(db, "Caroline is single", "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline is married", "2023-06-01T00:00:00+00:00")
    c3 = _capture(db, "Caroline is single", "2023-07-01T00:00:00+00:00")
    f1 = _fact(db, "Caroline is single", c1)
    f2 = _fact(db, "Caroline is married", c2)
    f3 = _fact(db, "Caroline is single", c3)

    consolidate(db[0], db[1])

    assert _active(db[0]) == ["Caroline is single"], _active(db[0])
    assert _row(db[0], f2)["status"] == "superseded"
    assert _row(db[0], f2)["superseded_by"] == f3
    assert _row(db[0], f1)["duplicate_of"] == f3
    assert _row(db[0], f3)["duplicate_of"] is None


def test_n1_duplicates_never_chain(db):
    """A duplicate must point at a live canonical row, not at another duplicate,
    or `duplicate_of` cannot be resolved in one hop."""
    c1 = _capture(db, "Caroline is single", "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline is single", "2023-05-15T00:00:00+00:00")
    c3 = _capture(db, "Caroline is single", "2023-05-20T00:00:00+00:00")
    ids = [_fact(db, "Caroline is single", c) for c in (c1, c2, c3)]
    dedupe(db[0], db[1])
    for fid in ids:
        row = _row(db[0], fid)
        if row["duplicate_of"] is not None:
            parent = _row(db[0], row["duplicate_of"])
            assert parent["duplicate_of"] is None, \
                "duplicate_of must name a canonical row, not another duplicate"


# ------------------------------------------------------------------ N2

def test_n2_locomo_stamp_normalised_and_ordered_correctly(db):
    """Tes N2: `1:56 pm on 8 May, 2023` was compared as a string against ISO
    stamps, so recency reversed. The stamp must normalise at ingest and the
    later claim must win."""
    c1 = _capture(db, "Caroline is single", "1:56 pm on 8 May, 2023")
    c2 = _capture(db, "Caroline is married", "1:14 pm on 25 May, 2023")
    f1 = _fact(db, "Caroline is single", c1)
    f2 = _fact(db, "Caroline is married", c2)

    stored = db[0].execute(
        "SELECT captured_at FROM captures WHERE id = ?", (c1,)).fetchone()[0]
    assert stored.startswith("2023-05-08"), stored

    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "superseded"
    assert _row(db[0], f1)["superseded_by"] == f2
    assert _row(db[0], f2)["status"] == "active"


def test_n2_slash_date_format_normalised(db):
    """The other stamp format in the corpus: `2023/04/10 (Mon) 17:50`."""
    cid = _capture(db, "Caroline is single", "2023/04/10 (Mon) 17:50")
    stored = db[0].execute(
        "SELECT captured_at, captured_at_text FROM captures WHERE id = ?",
        (cid,)).fetchone()
    assert stored["captured_at"].startswith("2023-04-10"), stored["captured_at"]
    assert stored["captured_at_text"] == "2023/04/10 (Mon) 17:50"


def test_n6_phrasing_variant_relationship_contradicts(db):
    """Found live on the GLM endpoint: "Caroline is single" and "Caroline got
    married in May 2023" keyed as `caroline is` and `caroline got`, so the
    contradiction was never compared and both stayed active. The slot key must
    identify the subject, not the verb phrase."""
    c1 = _capture(db, "Caroline is single", "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline got married in May 2023", "2023-06-01T00:00:00+00:00")
    c3 = _capture(db, "Caroline is single now", "2023-07-01T00:00:00+00:00")
    f1 = _fact(db, "Caroline is single", c1)
    f2 = _fact(db, "Caroline got married in May 2023", c2)
    f3 = _fact(db, "Caroline is single now", c3)
    consolidate(db[0], db[1])
    assert _active(db[0]) == ["Caroline is single now"], _active(db[0])
    assert _row(db[0], f2)["status"] == "superseded"
    assert _row(db[0], f2)["superseded_by"] == f3


# ------------------------------------------------------------------ N4

def test_n4_identity_sentences_do_not_flag_as_occupation(db):
    """Tes N4: `is a|is an` matched identity sentences, so 17 of 17 real flags
    were false. Two descriptions of the same subject must not flag."""
    c1 = _capture(db, "Cairnstone is an independent reimplementation of the capability",
                  "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Cairnstone is a local-first memory compiler",
                  "2023-06-01T00:00:00+00:00")
    _fact(db, "Cairnstone is an independent reimplementation of the capability", c1,
          path="projects/cairnstone", title="Cairnstone")
    _fact(db, "Cairnstone is a local-first memory compiler", c2,
          path="projects/cairnstone", title="Cairnstone")
    result = consolidate(db[0], db[1])
    assert result["flagged"] == 0, result


def test_n4_real_occupation_change_still_flags(db):
    """Tightening must not remove the signal: a genuine role change still flags."""
    c1 = _capture(db, "Caroline works as a nurse", "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline works as a teacher", "2023-06-01T00:00:00+00:00")
    _fact(db, "Caroline works as a nurse", c1)
    _fact(db, "Caroline works as a teacher", c2)
    result = consolidate(db[0], db[1])
    assert result["flagged"] == 1, result


# ------------------------------------------------------------------ N5

def test_n5_equal_timestamps_flag_without_superseding(db):
    """Policy P6: equal timestamps must be flagged with neither fact superseded."""
    stamp = "2023-06-01T10:00:00+00:00"
    c1 = _capture(db, "Caroline is single", stamp)
    c2 = _capture(db, "Caroline is married", stamp)
    f1 = _fact(db, "Caroline is single", c1)
    f2 = _fact(db, "Caroline is married", c2)
    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"
    assert db[0].execute(
        "SELECT COUNT(*) FROM change_events WHERE kind = 'fact.contradiction_flagged'"
    ).fetchone()[0] == 1


# ---------------------------------------------------------- migration backfill

def test_migration_backfills_compiled_at_for_captures_with_facts(tmp_path):
    """Tes review 2 item 5: a pre-phase-14 brain must not re-extract every
    capture on the first compile after upgrade."""
    path = str(tmp_path / "legacy.db")
    conn = store.init_db(path)
    ws = store.create_workspace(conn, "w")
    brain = store.create_brain(conn, ws, "b", "b")
    cid = store.add_capture(conn, brain, "conversation", "Caroline is single",
                            "src", captured_at="2023-05-01T00:00:00+00:00")
    page_id = store.create_page(conn, brain, "people/caroline", "people",
                                "Caroline", body_md="")
    version_id = conn.execute(
        "SELECT current_version_id FROM pages WHERE id = ?", (page_id,)).fetchone()[0]
    store.add_fact(conn, page_id, version_id, "Caroline is single", cid, 0, 17)
    # Simulate a legacy DB: the capture predates the compiled_at bookkeeping.
    conn.execute("UPDATE captures SET compiled_at = NULL WHERE id = ?", (cid,))
    conn.commit()
    conn.close()

    conn = store.init_db(path)  # runs the migration again
    row = conn.execute(
        "SELECT compiled_at FROM captures WHERE id = ?", (cid,)).fetchone()
    assert row["compiled_at"], "a capture that already has facts must be marked compiled"
    conn.close()
