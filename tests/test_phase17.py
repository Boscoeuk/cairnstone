"""Deterministic regression tests for the phase 17 fixes (F1-F4) from
`docs/phase17-brief.md` (defects found in reports/tes-review-4.md).

No model and no network: facts are written directly with store.add_fact, then
the consolidation functions run.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cairnstone import compile as comp
from cairnstone import store
from cairnstone.compile import consolidate


@pytest.fixture
def db(tmp_path):
    conn = store.init_db(str(tmp_path / "phase17.db"))
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


def _active(conn):
    return sorted(r["text"] for r in conn.execute(
        "SELECT text FROM facts WHERE status = 'active'"))


def _flags(conn):
    return conn.execute(
        "SELECT COUNT(*) AS n FROM change_events"
        " WHERE kind = 'fact.contradiction_flagged'").fetchone()["n"]


# ------------------------------------------------------------------ F3

def test_f3_phase_identifiers_stay_active(db):
    """F3(b): digits that are part of a name belong to the slot key. "Phase 1"
    and "Phase 2" name different phases; they must stay active — no supersede,
    no flag. Before the fix both keyed `phase was accepted after correction`
    with the number as the value, so the older phase was retired."""
    t1 = "Phase 1 was accepted after correction."
    t2 = "Phase 2 was accepted after correction."
    f1 = _fact(db, t1, _capture(db, t1, "2023-05-01T00:00:00+00:00"),
               path="projects/phase-1", title="phase 1")
    f2 = _fact(db, t2, _capture(db, t2, "2023-06-01T00:00:00+00:00"),
               path="projects/phase-1", title="phase 1")
    result = consolidate(db[0], db[1])
    assert result["superseded"] == 0, result
    assert result["flagged"] == 0, result
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"


def test_f3_budget_identifiers_stay_active(db):
    """F3(b): "budget 600" and "budget 1200" are different configurations, not
    one budget changing — the number after the label belongs to the key."""
    t1 = "Cairn at budget 600 scored 91.7% accuracy at 931 tokens"
    t2 = "Cairn at budget 1200 scored 91.7% accuracy at 1,613 tokens"
    f1 = _fact(db, t1, _capture(db, t1, "2023-05-01T00:00:00+00:00"),
               path="projects/cairn-rag", title="cairn-rag")
    f2 = _fact(db, t2, _capture(db, t2, "2023-06-01T00:00:00+00:00"),
               path="projects/cairn-rag", title="cairn-rag")
    result = consolidate(db[0], db[1])
    assert result["superseded"] == 0, result
    assert result["flagged"] == 0, result
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"


def test_f3_bare_as_of_suffix_is_not_a_value(db):
    """F3(a): a bare trailing "as of <date>" clause is a provenance stamp, not
    a differing value — the paraphrase must not flag or supersede; the two
    texts are one claim and dedupe links them."""
    t1 = "Caroline completed a triathlon"
    t2 = "Caroline completed a triathlon as of 2023-05-22"
    f1 = _fact(db, t1, _capture(db, t1, "2023-05-01T00:00:00+00:00"))
    f2 = _fact(db, t2, _capture(db, t2, "2023-06-01T00:00:00+00:00"))
    result = consolidate(db[0], db[1])
    assert result["flagged"] == 0, result
    assert result["superseded"] == 0, result
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"


def test_f3_genuine_value_change_still_supersedes(db):
    """F3 must not disable the pass: a real value change ("for 4 years" vs
    "for 5 years") still supersedes, and the Fitbit tenure shape survives."""
    t1 = "The user has been using a Fitbit Charge 3 for 6 months as of 2023-06-18"
    t2 = "The user has been using a Fitbit Charge 3 for 9 months as of 2023-09-02"
    f1 = _fact(db, t1, _capture(db, t1, "2023-06-18T00:00:00+00:00"))
    f2 = _fact(db, t2, _capture(db, t2, "2023-09-02T00:00:00+00:00"))
    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "superseded"
    assert _row(db[0], f1)["superseded_by"] == f2
    assert _row(db[0], f2)["status"] == "active"


# ------------------------------------------------------------------ F4

def test_f4_married_named_object_is_an_event(db):
    """F4: "X married Y" is a life event, so a later state retires the stale
    state but never the marriage record. Before the fix the marriage was not
    recognised as an event and was superseded by the later "single"."""
    t1 = "Caroline married Tomas in June 2023"
    t2 = "Caroline is single"
    f1 = _fact(db, t1, _capture(db, t1, "2023-06-01T00:00:00+00:00"))
    f2 = _fact(db, t2, _capture(db, t2, "2023-08-01T00:00:00+00:00"))
    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"
    assert _flags(db[0]) == 0


def test_f4_false_event_hits_do_not_make_states_permanent(db):
    """F4: "met" is dropped from the event marker, so a state sentence that
    contains it ("...met her husband through work and is married") is a state
    and IS retired by a later state. Before the fix the false event hit made
    the sentence permanently immune."""
    t1 = "Caroline met her husband through work and is married"
    t2 = "Caroline is single"
    f1 = _fact(db, t1, _capture(db, t1, "2023-05-01T00:00:00+00:00"))
    f2 = _fact(db, t2, _capture(db, t2, "2023-08-01T00:00:00+00:00"))
    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "superseded"
    assert _row(db[0], f1)["superseded_by"] == f2
    assert _row(db[0], f2)["status"] == "active"


def test_f4_event_marker_classification():
    """Unit view of the F4 marker decisions."""
    assert comp._is_event_fact("Caroline married Tomas in June 2023")
    assert comp._is_event_fact("Caroline wed Tomas")
    assert comp._is_event_fact("Caroline eloped")
    assert comp._is_event_fact("Caroline separated from Tomas")
    assert comp._is_event_fact("Caroline got engaged to Tomas")
    assert comp._is_event_fact("Caroline relocated to Lisbon")
    # the adjective form stays a state
    assert not comp._is_event_fact("Caroline is married")
    # dropped false hits
    assert not comp._is_event_fact("Caroline is left-handed")
    assert not comp._is_event_fact("the club she joined")
    assert not comp._is_event_fact(
        "Caroline met her husband through work and is married")
    # untouched marker entries
    assert comp._is_event_fact("Caroline got married on 2023-06-10")
    assert comp._is_event_fact("Caroline moved to Lisbon")


# ------------------------------------------------------------------ F1

def test_f1_fact_on_page_a_cannot_supersede_or_flag_a_fact_on_page_b(db):
    """Phase 17 F1: the contradiction scan resets its comparison state per page
    (policy P6). A fact on page A must be unable to supersede or flag a fact on
    page B, even when their slot keys collide.

    Before the fix one `claims` dict spanned the brain, so "Caroline is single"
    on people/caroline was retired by "Caroline is married" on misc/user.
    """
    c1 = _capture(db, "Caroline is single", "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline is married", "2023-06-01T00:00:00+00:00")
    f1 = _fact(db, "Caroline is single", c1, path="people/caroline")
    f2 = _fact(db, "Caroline is married", c2, path="misc/user",
               title="user")

    consolidate(db[0], db[1])

    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"
    assert _flags(db[0]) == 0


def test_f1_same_page_genuine_contradiction_still_supersedes(db):
    """The counter-case: on the SAME page a genuinely contradicting pair still
    supersedes — page scope must not disable the pass."""
    c1 = _capture(db, "Caroline is single", "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline is married", "2023-06-01T00:00:00+00:00")
    f1 = _fact(db, "Caroline is single", c1, path="people/caroline")
    f2 = _fact(db, "Caroline is married", c2, path="people/caroline")

    consolidate(db[0], db[1])

    assert _row(db[0], f1)["status"] == "superseded"
    assert _row(db[0], f1)["superseded_by"] == f2
    assert _row(db[0], f2)["status"] == "active"
