"""Deterministic regression tests for the phase 14 consolidation defects.

Each test reproduces a defect from reports/tes-consolidation-1.md without any
model or network: facts are written directly with store.add_fact and only the
consolidation functions run.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cairnstone import compile as comp
from cairnstone import retrieve, store
from cairnstone.compile import consolidate, dedupe, supersede_contradictions


@pytest.fixture
def db(tmp_path):
    conn = store.init_db(str(tmp_path / "phase14.db"))
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
    # Quote must be a verbatim substring of the capture; cite the whole capture.
    return store.add_fact(conn, page_id, version_id, text, capture_id,
                          0, max(1, len(content.strip())))


def _events(conn, kind):
    return conn.execute(
        "SELECT subject_id, payload_json FROM change_events WHERE kind = ?"
        " ORDER BY id", (kind,)).fetchall()


def _fact_row(conn, fact_id):
    return conn.execute("SELECT * FROM facts WHERE id = ?",
                        (fact_id,)).fetchone()


# ---------------------------------------------------------------- D1

def test_d1_duplicate_does_not_hide_canonical_fact_one_pass_converges(db):
    """D1: a duplicate row must not replace the canonical fact in the comparison
    map. One consolidation pass supersedes the canonical stale fact; a second
    pass changes nothing."""
    conn, brain = db
    c1 = _capture(db, "Caroline is single", "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline is single", "2023-05-15T00:00:00+00:00")
    c3 = _capture(db, "Caroline is married", "2023-06-01T00:00:00+00:00")
    f1 = _fact(db, "Caroline is single", c1)
    f2 = _fact(db, "Caroline is single", c2)
    f3 = _fact(db, "Caroline is married", c3)
    assert dedupe(conn, brain) == 1
    # Phase 15 (N1): the canonical row is the LATEST capture, so f1 (May 1) is
    # linked as a duplicate of f2 (May 15) — not the other way round.
    assert _fact_row(conn, f1)["duplicate_of"] == f2
    assert _fact_row(conn, f2)["duplicate_of"] is None

    linked, superseded, flagged = consolidate(conn, brain).values()
    assert (linked, superseded, flagged) == (0, 1, 0)
    # The canonical fact f2 — not just a duplicate — is superseded in ONE pass.
    assert _fact_row(conn, f2)["status"] == "superseded"
    assert _fact_row(conn, f2)["superseded_by"] == f3
    # No canonical ('single') fact contradicts 'married' any more; the only
    # remaining active 'single' row is f2, a duplicate excluded from briefs and
    # export by eligible_facts (P8).
    active_canonical = [r["text"] for r in conn.execute(
        "SELECT text FROM facts WHERE status = 'active'"
        " AND duplicate_of IS NULL")]
    assert "Caroline is single" not in active_canonical
    assert conn.execute(
        "SELECT COUNT(*) FROM facts WHERE status = 'active'"
        " AND duplicate_of IS NOT NULL").fetchone()[0] == 1

    # Idempotent: a second pass changes nothing.
    before = conn.execute(
        "SELECT id, status, superseded_by, duplicate_of FROM facts ORDER BY id"
    ).fetchall()
    events_before = conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0]
    result = consolidate(conn, brain)
    assert result == {"duplicates_linked": 0, "superseded": 0, "flagged": 0}
    after = conn.execute(
        "SELECT id, status, superseded_by, duplicate_of FROM facts ORDER BY id"
    ).fetchall()
    assert before == after
    assert conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0] \
        == events_before


# ---------------------------------------------------------------- D3

def test_d3_out_of_order_captures_supersede_by_captured_at(db):
    """D3: a backfilled older capture must lose to a later captured_at, even
    though it was ingested with a higher capture id."""
    conn, brain = db
    # Ingestion order: c1 (June) first, then the backfilled c2 (May).
    c1 = _capture(db, "Caroline has been a nurse for 5 years",
                  "2023-06-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline has been a nurse for 4 years",
                  "2023-05-01T00:00:00+00:00")
    assert c2 > c1  # higher capture id, earlier timestamp
    f1 = _fact(db, "Caroline has been a nurse for 5 years", c1)
    f2 = _fact(db, "Caroline has been a nurse for 4 years", c2)

    superseded = supersede_contradictions(conn, brain)
    assert superseded == 1
    # The May fact is superseded by the June fact — not the other way round.
    assert _fact_row(conn, f2)["status"] == "superseded"
    assert _fact_row(conn, f2)["superseded_by"] == f1
    assert _fact_row(conn, f1)["status"] == "active"
    assert _fact_row(conn, f1)["superseded_by"] is None


def test_d3_equal_timestamps_flag_under_policy_p6(db):
    """D3 tie-break, superseded by phase 15 N5: when two captures share the same
    instant, policy P6 says flag the contradiction and supersede neither. The
    capture-id tie-break still orders *different* timestamps, but an exact tie is
    ambiguity, not a race."""
    conn, brain = db
    c1 = _capture(db, "Caroline is single", "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline is married", "2023-05-01T00:00:00+00:00")
    f1 = _fact(db, "Caroline is single", c1)
    f2 = _fact(db, "Caroline is married", c2)
    supersede_contradictions(conn, brain)
    assert _fact_row(conn, f1)["status"] == "active"
    assert _fact_row(conn, f2)["status"] == "active"
    assert _fact_row(conn, f1)["superseded_by"] is None
    assert _fact_row(conn, f2)["superseded_by"] is None
    assert conn.execute(
        "SELECT COUNT(*) FROM change_events WHERE kind = 'fact.contradiction_flagged'"
    ).fetchone()[0] == 1


# ---------------------------------------------------------------- D4

def test_d4_swap_keeps_value_and_row_agreeing_no_self_supersede(db):
    """D4: with fact ids out of capture order, the swap path must store the
    value that belongs to the surviving row, so a following same-capture fact
    is never judged a contradiction of itself."""
    conn, brain = db
    c1 = _capture(db, "Caroline is single", "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline is married", "2023-06-01T00:00:00+00:00")
    # Fact id order deliberately crosses capture order: f1 cites c2 (June),
    # f2 cites c1 (May), f3 cites c2 again.
    f1 = _fact(db, "Caroline is married", c2)
    f2 = _fact(db, "Caroline is single", c1)
    f3 = _fact(db, "Caroline is married and happy", c2)

    superseded = supersede_contradictions(conn, brain)
    assert superseded == 1  # only single -> married
    # f2 (May, single) superseded by f1 (June, married): correct direction.
    assert _fact_row(conn, f2)["status"] == "superseded"
    assert _fact_row(conn, f2)["superseded_by"] == f1
    # f1 agrees with f3 (both 'married'): never superseded by its own claim.
    assert _fact_row(conn, f1)["status"] == "active"
    assert _fact_row(conn, f1)["superseded_by"] is None
    assert _fact_row(conn, f3)["status"] == "active"


def test_d4_fact_never_superseded_by_duplicate_of_itself(db):
    """D4 consequence: a fact must never be superseded by a duplicate of itself,
    which previously hid the claim from briefs and export."""
    conn, brain = db
    c1 = _capture(db, "Caroline got married", "2023-05-27T00:00:00+00:00")
    c2 = _capture(db, "Caroline is married", "2023-06-01T00:00:00+00:00")
    f1 = _fact(db, "Caroline is married", c2)
    f2 = _fact(db, "Caroline is married", c1)
    f3 = _fact(db, "Caroline is married", c2)
    dedupe(conn, brain)  # f2 and f3 link to f1 (same claim, same value)
    supersede_contradictions(conn, brain)
    for fid in (f1, f2, f3):
        row = _fact_row(conn, fid)
        if row["status"] == "superseded":
            assert row["superseded_by"] != fid
    # The canonical 'married' claim survives active.
    assert _fact_row(conn, f1)["status"] == "active"


# ---------------------------------------------------------------- D5

def test_d5_location_contradiction_flagged_not_silent(db):
    """D5: a location change is compared on the extracted value and recorded as
    an advisory fact.contradiction_flagged event; neither fact is retracted."""
    conn, brain = db
    c1 = _capture(db, "Caroline lives in Berlin", "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline lives in Lisbon", "2023-06-01T00:00:00+00:00")
    f1 = _fact(db, "Caroline lives in Berlin", c1)
    f2 = _fact(db, "Caroline lives in Lisbon", c2)

    result = consolidate(conn, brain)
    assert result["flagged"] == 1
    assert result["superseded"] == 0
    # Advisory: both facts stay active and visible.
    assert _fact_row(conn, f1)["status"] == "active"
    assert _fact_row(conn, f2)["status"] == "active"
    events = _events(conn, "fact.contradiction_flagged")
    assert len(events) == 1
    subject_id, payload = events[0]["subject_id"], json.loads(events[0]["payload_json"])
    assert subject_id == f1  # the older fact carries the flag
    assert payload["contradicts"] == f2
    assert payload["values"] == [["berlin"], ["lisbon"]]

    # Idempotent: a second pass writes no duplicate flag.
    assert consolidate(conn, brain)["flagged"] == 0
    assert len(_events(conn, "fact.contradiction_flagged")) == 1


def test_d5_occupation_rewording_not_flagged_when_values_agree(db):
    """D5(a): 'working as a nurse for 4 years' and 'is a nurse' extract the same
    occupation value, so rewording alone is not a contradiction."""
    conn, brain = db
    c1 = _capture(db, "Caroline has been working as a nurse for 4 years",
                  "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline is a nurse", "2023-06-01T00:00:00+00:00")
    _fact(db, "Caroline has been working as a nurse for 4 years", c1)
    _fact(db, "Caroline is a nurse", c2)
    result = consolidate(conn, brain)
    assert result["superseded"] == 0
    assert result["flagged"] == 0


def test_d5_occupation_change_flagged(db):
    conn, brain = db
    c1 = _capture(db, "Caroline is a nurse", "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline is a teacher", "2023-06-01T00:00:00+00:00")
    f1 = _fact(db, "Caroline is a nurse", c1)
    f2 = _fact(db, "Caroline is a teacher", c2)
    result = consolidate(conn, brain)
    assert result["flagged"] == 1
    assert _fact_row(conn, f1)["status"] == "active"
    assert _fact_row(conn, f2)["status"] == "active"


# ------------------------------------------------- spelling-variant dedupe

def test_spelling_variants_link_as_duplicates(db):
    """Near-duplicate detection: 'favourite'/'favorite' (and case/punctuation
    differences) fold to one claim key."""
    conn, brain = db
    c1 = _capture(db, "Caroline's favourite hobby is painting landscapes",
                  "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline's favorite hobby is painting landscapes",
                  "2023-06-01T00:00:00+00:00")
    f1 = _fact(db, "Caroline's favourite hobby is painting landscapes", c1)
    f2 = _fact(db, "Caroline's favorite hobby is painting landscapes", c2)
    assert dedupe(conn, brain) == 1
    # Phase 15 (N1): the later capture (June) is canonical, so the May fact is
    # the duplicate. Linking either way proves the spelling fold works; which
    # one is canonical is decided by capture time, not fact id.
    assert _fact_row(conn, f1)["duplicate_of"] == f2
    assert _fact_row(conn, f2)["duplicate_of"] is None


# ---------------------------------------------------------------- D6

def _fake_embeddings(monkeypatch, dim=8):
    def fake(texts):
        vecs = []
        for t in texts:
            h = hash(t) & 0xFFFFFFFF
            v = [((h >> (i % 32)) & 1) * 1.0 + 0.1 for i in range(dim)]
            norm = sum(x * x for x in v) ** 0.5
            vecs.append([x / norm for x in v])
        return vecs
    monkeypatch.setattr(retrieve, "_request_embeddings", fake)


def test_d6_brief_prefers_new_side_of_undetected_contradiction(db, monkeypatch):
    """D6: the near-duplicate collapse must not serve the stale side. After the
    move, the brief for 'Where does Caroline live?' carries Lisbon."""
    conn, brain = db
    c1 = _capture(db, "Caroline lives in Berlin", "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, "Caroline lives in Lisbon", "2023-06-01T00:00:00+00:00")
    _fact(db, "Caroline lives in Berlin", c1)
    _fact(db, "Caroline lives in Lisbon", c2)
    consolidate(conn, brain)  # flags, keeps both active

    _fake_embeddings(monkeypatch)
    _stable, _volatile, selected = retrieve.build_brief(
        conn, brain, "Where does Caroline live?")
    texts = [f["text"] for f in selected]
    assert any("Lisbon" in t for t in texts)
    # Phase 15 (N3): the flagged contradiction must stay visible to a reader
    # rather than being silently dropped by the collapse. Berlin is still the
    # older, unresolved fact, so it is present AND labelled as contradicting.
    assert any("Berlin" in t for t in texts)
    assert "contradict" in _volatile.lower()


# ------------------------------------------------- D2 compile bookkeeping

def test_d2_compiled_captures_not_reprocessed(db):
    """D2: compile_capture records compiled_at, so an incremental compile
    selects only uncompiled captures."""
    conn, brain = db
    c1 = _capture(db, "Caroline lives in Berlin", "2023-05-01T00:00:00+00:00")

    class FakeClient:
        def chat(self, messages, model=None, max_tokens=1024, think=False,
                 temperature=0.0):
            return ('{"facts": [{"text": "Caroline lives in Berlin",'
                    ' "subject": "Caroline", "quote": "Caroline lives in Berlin",'
                    ' "bucket": "people", "page_title": "Caroline",'
                    ' "page_path": "people/caroline"}]}')

    result = comp.compile_capture(conn, brain, c1, FakeClient())
    assert result["ok"] and result["accepted"] == 1
    row = conn.execute("SELECT compiled_at FROM captures WHERE id = ?",
                       (c1,)).fetchone()
    assert row["compiled_at"] is not None
    pending = [r["id"] for r in conn.execute(
        "SELECT id FROM captures WHERE brain_id = ? AND compiled_at IS NULL",
        (brain,))]
    assert pending == []
