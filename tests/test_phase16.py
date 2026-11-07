"""Deterministic regression tests for the phase 16 defects (N7-N11) found in
reports/tes-review-3.md at HEAD d73b6ae.

No model and no network: captures and facts are written with store.add_capture /
store.add_fact, then the consolidation and brief code runs over them. Each test
is written to FAIL at d73b6ae and pass once the phase-16 fixes are in.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cairnstone import cli, retrieve, store
from cairnstone.compile import PolicyHalt, _fact_slots, consolidate


@pytest.fixture
def db(tmp_path):
    conn = store.init_db(str(tmp_path / "phase16.db"))
    ws = store.create_workspace(conn, "w")
    brain = store.create_brain(conn, ws, "b", "b")
    yield conn, brain
    conn.close()


def _capture(db, text, captured_at=None):
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
    return conn.execute("SELECT * FROM facts WHERE id = ?",
                        (fact_id,)).fetchone()


def _active(conn):
    return [r["text"] for r in conn.execute(
        "SELECT text FROM facts WHERE status = 'active'"
        " AND duplicate_of IS NULL ORDER BY id")]


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


# --------------------------------------------------------------------- N7
# Slot keys carried extractor phrasing, so two statements of one fact never
# shared a key and the stale value stayed active.

def test_n7_duration_paraphrase_supersedes_stale_value(db):
    """`... for 4 years as of 2023-05-08` and `... for 5 years` are the same
    claim about the same slot. At d73b6ae the first key kept the "as of - - ."
    fragments, so the two never compared and both stayed active."""
    t1 = "Caroline has been working as a nurse for 4 years as of 2023-05-08"
    t2 = "Caroline has been working as a nurse for 5 years"
    f1 = _fact(db, t1, _capture(db, t1, "2023-05-08T00:00:00+00:00"))
    f2 = _fact(db, t2, _capture(db, t2, "2023-06-08T00:00:00+00:00"))
    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "superseded"
    assert _row(db[0], f1)["superseded_by"] == f2
    assert _row(db[0], f2)["status"] == "active"


def test_n7_child_count_keys_collapse(db):
    """`1 child` and `2 children` must key identically; X2 scored 6/6 wrong
    because the plural split the slot."""
    t1 = "Caroline has 1 child"
    t2 = "Caroline has 2 children"
    f1 = _fact(db, t1, _capture(db, t1, "2023-05-01T00:00:00+00:00"))
    f2 = _fact(db, t2, _capture(db, t2, "2023-06-01T00:00:00+00:00"))
    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "superseded"
    assert _row(db[0], f1)["superseded_by"] == f2


def test_n7_occupation_slot_keys_on_subject_not_phrasing(db):
    """`_subject_prefix` kept "has been working as", so the occupation slot was
    `cat:occupation:caroline has been` and never matched `cat:occupation:caroline`."""
    slots = dict(_fact_slots("Caroline has been working as a nurse"))
    assert slots.get("cat:occupation:caroline") == ("nurse",), slots
    assert "cat:occupation:caroline has been" not in slots, slots
    # The same slot from the plain phrasing, so a rewording compares.
    assert dict(_fact_slots("Caroline is a nurse")).get(
        "cat:occupation:caroline") == ("nurse",)


def test_n7_numeric_key_carries_no_phrasing_fragments(db):
    """A dated numeric slot must key on content words only: no "as of", no
    punctuation fragments left behind by value-token removal."""
    key = [k for k, _v in _fact_slots(
        "Caroline has been working as a nurse for 4 years as of 2023-05-08")
        if not k.startswith("cat:")]
    assert key == ["caroline nurse year"], key


# --------------------------------------------------------------------- N8
# "Earlier" was assigned by position in `selected`, not by captured_at, so the
# newer fact was labelled "Earlier".

def test_n8_earlier_marker_follows_capture_stamp(db, monkeypatch):
    conn, brain = db
    t1 = "Caroline is single"
    t2 = "Caroline is married"
    _fact(db, t1, _capture(db, t1, "2023-05-01T00:00:00+00:00"))
    _fact(db, t2, _capture(db, t2, "2023-06-01T00:00:00+00:00"))
    _fake_embeddings(monkeypatch)
    _stable, volatile, _selected = retrieve.build_brief(
        conn, brain, "What is Caroline's marital status?")
    assert "Earlier: Caroline is single (contradicts Caroline is married)" \
        in volatile, volatile
    assert "Earlier: Caroline is married" not in volatile, volatile


def test_n8_resolved_pair_is_not_labelled(db, monkeypatch):
    """A superseded fact is history, not a live contradiction; with the history
    included in the candidate set the brief must not claim one is "Earlier"."""
    conn, brain = db
    t1 = "Caroline is single"
    t2 = "Caroline is married"
    _fact(db, t1, _capture(db, t1, "2023-05-01T00:00:00+00:00"))
    _fact(db, t2, _capture(db, t2, "2023-06-01T00:00:00+00:00"))
    consolidate(conn, brain)  # resolves the pair
    _fake_embeddings(monkeypatch)
    _stable, volatile, _selected = retrieve.build_brief(
        conn, brain, "Was Caroline married in the past?")
    assert "contradict" not in volatile.lower(), volatile


def test_n8_event_vs_state_pair_is_not_a_brief_contradiction(db, monkeypatch):
    """An older marriage event and a later "is single" share the relationship
    slot but are not a contradiction, so the brief must not claim one."""
    conn, brain = db
    t_event = "Caroline got married on 2023-06-10"
    t_single = "Caroline is single"
    _fact(db, t_event, _capture(db, t_event, "2023-06-10T00:00:00+00:00"))
    _fact(db, t_single, _capture(db, t_single, "2023-08-01T00:00:00+00:00"))
    consolidate(conn, brain)
    _fake_embeddings(monkeypatch)
    _stable, volatile, _selected = retrieve.build_brief(
        conn, brain, "Is Caroline married?")
    assert "contradict" not in volatile.lower(), volatile


def test_n8_uncomparable_stamps_are_labelled_unresolved(db, monkeypatch):
    """When the two capture stamps cannot be ordered (here: identical), the
    brief must not claim one is "Earlier" — it says Unresolved."""
    conn, brain = db
    t1 = "Caroline is single"
    t2 = "Caroline is married"
    _fact(db, t1, _capture(db, t1, "2023-05-01T00:00:00+00:00"))
    _fact(db, t2, _capture(db, t2, "2023-05-01T00:00:00+00:00"))
    _fake_embeddings(monkeypatch)
    _stable, volatile, _selected = retrieve.build_brief(
        conn, brain, "What is Caroline's marital status?")
    assert "Unresolved:" in volatile, volatile
    assert "capture times not comparable" in volatile, volatile
    assert "Earlier:" not in volatile, volatile


# --------------------------------------------------------------------- N9
# An undated capture defaulted to "now" and so beat dated history.

def test_n9_undated_capture_does_not_beat_dated_history(db):
    t1 = "Caroline is married"
    t2 = "Caroline is single"
    f1 = _fact(db, t1, _capture(db, t1, "2023-01-01T00:00:00+00:00"))
    f2 = _fact(db, t2, _capture(db, t2, None))  # ingested now, undated
    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "superseded"
    assert _row(db[0], f2)["superseded_by"] == f1


def test_n9_add_capture_records_explicit_flag(db):
    conn, brain = db
    dated = store.add_capture(conn, brain, "note", "a", "s",
                              captured_at="2023-05-01T00:00:00+00:00")
    undated = store.add_capture(conn, brain, "note", "b", "s")
    junk = store.add_capture(conn, brain, "note", "c", "s",
                             captured_at="next tuesday")
    flags = {r["id"]: r["captured_at_explicit"] for r in conn.execute(
        "SELECT id, captured_at_explicit FROM captures")}
    assert flags[dated] == 1
    assert flags[undated] == 0
    assert flags[junk] == 0
    assert conn.execute("SELECT captured_at_text FROM captures WHERE id = ?",
                        (junk,)).fetchone()[0] == "next tuesday"


def test_n9_legacy_rows_keep_a_usable_stamp(tmp_path):
    """A database created before phase 16 has no `captured_at_explicit`; its
    stored stamps are the best evidence available, so the migration must not
    demote every existing capture to "undated"."""
    dbpath = str(tmp_path / "legacy.db")
    conn = store.init_db(dbpath)
    brain = store.create_brain(conn, store.create_workspace(conn, "w"), "b", "b")
    capture_id = store.add_capture(conn, brain, "note", "a", "s",
                                   captured_at="2023-05-01T00:00:00+00:00")
    conn.execute("ALTER TABLE captures DROP COLUMN captured_at_explicit")
    conn.commit()
    conn.close()
    conn = store.init_db(dbpath)
    row = conn.execute("SELECT captured_at_explicit FROM captures WHERE id = ?",
                       (capture_id,)).fetchone()
    conn.close()
    assert row[0] == 1


def _ingest(dbpath, tmp_path, text="hello", captured_at=None):
    path = tmp_path / "n.txt"
    path.write_text(text, encoding="utf-8")
    argv = ["ingest", "--db", dbpath, "--kind", "note", "--source", "s",
            "--file", str(path)]
    if captured_at is not None:
        argv += ["--captured-at", captured_at]
    return cli.main(argv)


def test_n9_ingest_warns_on_stderr_without_captured_at(tmp_path, capsys):
    dbpath = str(tmp_path / "n9.db")
    assert cli.main(["init", "--db", dbpath]) == 0
    assert _ingest(dbpath, tmp_path) == 0
    err = capsys.readouterr().err
    assert "warning:" in err and "captured-at" in err, err


def test_n9_ingest_warns_on_unparseable_captured_at(tmp_path, capsys):
    dbpath = str(tmp_path / "n9b.db")
    assert cli.main(["init", "--db", dbpath]) == 0
    assert _ingest(dbpath, tmp_path, captured_at="next tuesday") == 0
    err = capsys.readouterr().err
    assert "warning:" in err and "next tuesday" in err, err
    conn = store.init_db(dbpath)
    row = conn.execute("SELECT captured_at_text, captured_at_explicit"
                       " FROM captures").fetchone()
    conn.close()
    assert row["captured_at_text"] == "next tuesday"
    assert row["captured_at_explicit"] == 0


def test_n9_parseable_captured_at_is_silent(tmp_path, capsys):
    dbpath = str(tmp_path / "n9c.db")
    assert cli.main(["init", "--db", dbpath]) == 0
    assert _ingest(dbpath, tmp_path, captured_at="2023-05-01") == 0
    assert "warning:" not in capsys.readouterr().err


# -------------------------------------------------------------------- N10
# A pass over max_mutation_rate applied every mutation and then raised, so the
# halted pass became permanent without review.

def test_n10_halt_rolls_back_the_whole_pass(db):
    t1 = "Caroline is single"
    t2 = "Caroline is married"
    f1 = _fact(db, t1, _capture(db, t1, "2023-05-01T00:00:00+00:00"))
    f2 = _fact(db, t2, _capture(db, t2, "2023-06-01T00:00:00+00:00"))
    with pytest.raises(PolicyHalt):
        consolidate(db[0], db[1], max_mutation_rate=0.0)
    # Nothing applied: the brain is exactly as it was.
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"
    assert db[0].execute("SELECT COUNT(*) FROM change_events WHERE kind ="
                         " 'fact.superseded'").fetchone()[0] == 0
    # And the next pass halts again rather than reporting superseded=0.
    with pytest.raises(PolicyHalt):
        consolidate(db[0], db[1], max_mutation_rate=0.0)
    assert _active(db[0]) == [t1, t2]


def test_n10_cli_reports_halt_without_applying(tmp_path, capsys):
    dbpath = str(tmp_path / "n10.db")
    assert cli.main(["init", "--db", dbpath]) == 0
    t1, t2 = "Caroline is single", "Caroline is married"
    assert _ingest(dbpath, tmp_path, text=t1,
                   captured_at="2023-05-01T00:00:00+00:00") == 0
    assert _ingest(dbpath, tmp_path, text=t2,
                   captured_at="2023-06-01T00:00:00+00:00") == 0
    # Facts are written directly: the CLI ingest path only stores captures.
    conn = store.init_db(dbpath)
    brain = conn.execute("SELECT id FROM brains LIMIT 1").fetchone()[0]
    page_id = store.create_page(conn, brain, "people/caroline", "people",
                                "Caroline", body_md="")
    version_id = conn.execute("SELECT current_version_id FROM pages WHERE id = ?",
                              (page_id,)).fetchone()[0]
    caps = conn.execute("SELECT id FROM captures ORDER BY id").fetchall()
    store.add_fact(conn, page_id, version_id, t1, caps[0]["id"], 0, len(t1))
    store.add_fact(conn, page_id, version_id, t2, caps[1]["id"], 0, len(t2))
    conn.close()
    capsys.readouterr()

    assert cli.main(["consolidate", "--db", dbpath,
                     "--max-mutation-rate", "0"]) == 1
    out = capsys.readouterr().out
    assert "error:" in out and "halted for review" in out, out
    conn = store.init_db(dbpath)
    statuses = [r["status"] for r in conn.execute(
        "SELECT status FROM facts ORDER BY id")]
    conn.close()
    assert statuses == ["active", "active"], statuses


# -------------------------------------------------------------------- N11
# After "split up / single again", "Caroline's spouse is Tomas" stayed active
# and the historical marriage event was superseded as if it were a state.

def test_n11_spouse_split_retires_states_and_keeps_the_event(db):
    t_spouse = "Caroline's spouse is Tomas"
    t_married = "Caroline is married"
    t_event = "Caroline got married on 2023-06-10"
    t_single = "Caroline is single"
    f_spouse = _fact(db, t_spouse, _capture(db, t_spouse, "2023-05-01T00:00:00+00:00"))
    f_married = _fact(db, t_married, _capture(db, t_married, "2023-06-01T00:00:00+00:00"))
    f_event = _fact(db, t_event, _capture(db, t_event, "2023-06-10T00:00:00+00:00"))
    f_single = _fact(db, t_single, _capture(db, t_single, "2023-08-01T00:00:00+00:00"))
    consolidate(db[0], db[1])
    assert _row(db[0], f_spouse)["status"] == "superseded"
    assert _row(db[0], f_spouse)["superseded_by"] == f_single
    assert _row(db[0], f_married)["status"] == "superseded"
    assert _row(db[0], f_married)["superseded_by"] == f_single
    assert _row(db[0], f_event)["status"] == "active"
    assert _row(db[0], f_single)["status"] == "active"


def test_n11_event_not_flagged_against_a_later_state(db):
    """The event-versus-state pair must not raise an advisory flag either: a
    marriage in June is not a contradiction of being single in August."""
    t_event = "Caroline got married on 2023-06-10"
    t_single = "Caroline is single"
    _fact(db, t_event, _capture(db, t_event, "2023-06-10T00:00:00+00:00"))
    _fact(db, t_single, _capture(db, t_single, "2023-08-01T00:00:00+00:00"))
    consolidate(db[0], db[1])
    flags = db[0].execute(
        "SELECT COUNT(*) FROM change_events WHERE kind ="
        " 'fact.contradiction_flagged'").fetchone()[0]
    assert flags == 0
