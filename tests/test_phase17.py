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


# ------------------------------------------------------- D1 (tes-review-5)

# Same-page, older -> newer knowledge updates from Tes review 5 D1: at d9a4da7
# eight of these twelve stopped superseding because F3b froze the count into
# the slot key ("owns 15" and "owns 17" were different claims). A verb or
# quantifier before a number is a VALUE context, not an identifier label.
D1_COUNT_UPDATES = [
    ("The user owns 15 Funko Pops", "The user owns 17 Funko Pops"),
    ("The user has 3 cats", "The user has 4 cats"),
    ("The user has read 12 books this year",
     "The user has read 15 books this year"),
    ("The user ran 5 km on Saturday", "The user ran 10 km on Saturday"),
    ("The user's personal best 5K time is 25 minutes",
     "The user's personal best 5K time is 23 minutes"),
    ("The user has recorded over 30 bird species",
     "The user has recorded over 45 bird species"),
    ("The user practices guitar for at least 30 minutes every day",
     "The user practices guitar for at least 45 minutes every day"),
    ("The user has watched 12 episodes of The Crown",
     "The user has watched 20 episodes of The Crown"),
    ("The user's rent is 1200 per month",
     "The user's rent is 1400 per month"),
    ("The user completed 70% of the storyline",
     "The user completed 90% of the storyline"),
    ("The user's Instagram has 500 followers",
     "The user's Instagram has 650 followers"),
    ("The user saved 300 dollars for the trip",
     "The user saved 450 dollars for the trip"),
]


@pytest.mark.parametrize("older,newer", D1_COUNT_UPDATES)
def test_d1_count_update_after_a_verb_still_supersedes(db, older, newer):
    """Tes review 5 D1: a count that follows a verb or a quantifier is a value,
    so a later, different count must supersede it. At d9a4da7 the number was
    frozen into the key and the update never resolved (8 of these 12 were
    active together)."""
    f1 = _fact(db, older, _capture(db, older, "2023-05-01T00:00:00+00:00"),
               path="people/user", title="user")
    f2 = _fact(db, newer, _capture(db, newer, "2023-08-01T00:00:00+00:00"),
               path="people/user", title="user")
    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "superseded"
    assert _row(db[0], f1)["superseded_by"] == f2
    assert _row(db[0], f2)["status"] == "active"


def test_d1_verb_and_quantifier_labels_do_not_enter_the_key():
    """Unit view: the numbers after a verb or quantifier are values, so the two
    texts key identically; identifier labels still key apart."""
    assert (comp._split_subject_slot("The user owns 15 Funko Pops")[0]
            == comp._split_subject_slot("The user owns 17 Funko Pops")[0])
    assert (comp._split_subject_slot("The user has read 12 books this year")[0]
            == comp._split_subject_slot("The user has read 15 books this year")[0])
    assert comp._split_subject_slot("The user ran 5 km")[1] == ("5",)
    assert comp._split_subject_slot("The user has recorded over 30 bird species")[1] \
        == ("30",)
    # Identifier labels are unchanged: phase/conv/budget/attached digits stay
    # part of the name, so those pairs keep distinct keys.
    assert (comp._split_subject_slot("Phase 1 was accepted")[0]
            != comp._split_subject_slot("Phase 2 was accepted")[0])
    assert (comp._split_subject_slot("conv-26 baseline")[0]
            != comp._split_subject_slot("conv-30 baseline")[0])
    assert (comp._split_subject_slot("budget 600 run")[0]
            != comp._split_subject_slot("budget 1200 run")[0])
    assert (comp._split_subject_slot("b600 run")[0]
            != comp._split_subject_slot("b1200 run")[0])
    # A month/weekday is a value, not a label.
    assert comp._split_subject_slot("Billing v2 ships Mar 31")[1] == ("mar", "31")


# ----------------------------------------------------- D2/D3 (tes-review-5)

# Same-page, older -> newer pairs where the later fact carries an INCIDENTAL
# relationship word. At d9a4da7 the F4 subject cut put each of these on the
# subject's bare relationship slot, so the later fact superseded a true status.
D2_INCIDENTAL_PAIRS = [
    ("The user is married",
     "The user is working on new comedy material about online dating"),
    ("The user is married",
     "User has been using a single-action airbrush so far"),
    ("The user is married",
     "User is planning a themed dinner party and asked for ideas to keep "
     "guests engaged"),
    ("The user is single",
     "The user bought a gift for her friend who is getting married"),
    ("The user is single", "The user works with a colleague who is divorced"),
    ("Caroline is married", "Caroline is planning to become a single parent"),
    ("Caroline is married", "Caroline is thinking about becoming a single parent"),
    ("Caroline is married", "Caroline is becoming a single parent"),
    ("Caroline is married", "Caroline plans to become a single parent"),
    ("Caroline is married", "Caroline wants to adopt as a single parent"),
]


@pytest.mark.parametrize("status,incidental", D2_INCIDENTAL_PAIRS)
def test_d2_incidental_category_word_does_not_supersede_status(db, status,
                                                               incidental):
    """Tes review 5 D2: only a main-clause predicate forms the relationship
    slot. A relative clause, a prepositional phrase or a noun modifier must not
    retire the subject's true status."""
    path = "people/caroline" if status.startswith("Caroline") else "people/user"
    title = "Caroline" if status.startswith("Caroline") else "user"
    f1 = _fact(db, status, _capture(db, status, "2023-05-01T00:00:00+00:00"),
               path=path, title=title)
    f2 = _fact(db, incidental,
               _capture(db, incidental, "2023-08-01T00:00:00+00:00"),
               path=path, title=title)
    result = consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"
    assert _row(db[0], f1)["superseded_by"] is None
    assert result["superseded"] == 0, result
    assert result["flagged"] == 0, result


def test_d2_relationship_slot_requires_a_main_clause_predicate():
    """Unit view of the D2 predicate rule: accepted shapes form the slot,
    incidental shapes form none."""
    assert comp._relationship_status_slot("Caroline is married") == \
        ("caroline", "married")
    assert comp._relationship_status_slot("Caroline got married in May 2023") == \
        ("caroline", "married")
    assert comp._relationship_status_slot("Caroline is now dating someone") == \
        ("caroline", "dating")
    assert comp._relationship_status_slot("Caroline is happily married") == \
        ("caroline", "married")
    assert comp._relationship_status_slot("The user got married recently") == \
        ("the user", "married")
    assert comp._relationship_status_slot(
        "Caroline has been married for five years") == ("caroline", "married")
    assert comp._relationship_status_slot(
        "The user has been single since 2020") == ("the user", "single")
    assert comp._relationship_status_slot(
        "Pocahontas married John Rolfe in 1614") == ("pocahontas", "married")
    assert comp._relationship_status_slot(
        "Caroline met her husband through work and is married") == \
        ("caroline", "married")
    # Rejected: relative clauses, prepositional phrases, noun modifiers, plans.
    for text in (
        "The user is working on new comedy material about online dating",
        "User has been using a single-action airbrush so far",
        "User is planning a themed dinner party to keep guests engaged",
        "The user bought a gift for her friend who is getting married",
        "The user works with a colleague who is divorced",
        "Caroline is planning to become a single parent",
        "Caroline is becoming a single parent",
        "Caroline is getting married",
        "Caroline wants to adopt as a single parent",
        "Kikuchi-san and Fumiya Tomozaki started dating after the festival",
        "User reflected on their dating history",
        "The user is happy that her sister is married",
    ):
        assert comp._relationship_status_slot(text) is None, text


def test_d3_caroline_residual_is_not_a_supersession_with_later_stamps(db):
    """Tes review 5 D3: the documented Caroline residual is a SUPERSESSION, not
    just a flag, once the timestamps differ. In the dogfood DB the two captures
    share a date, so only a flag showed up. With a later stamp on "becoming a
    single parent" the true status must stay active."""
    t1 = "Caroline is married"
    t2 = "Caroline is becoming a single parent"
    f1 = _fact(db, t1, _capture(db, t1, "2023-05-01T00:00:00+00:00"))
    f2 = _fact(db, t2, _capture(db, t2, "2023-08-01T00:00:00+00:00"))
    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"
    assert _row(db[0], f1)["superseded_by"] is None
    assert _flags(db[0]) == 0
    # The transition is not a relationship claim at all.
    assert ("cat:relationship_status:caroline", "single") not in \
        comp._fact_slots(t2)
    assert ("cat:relationship_status:caroline", "married") in \
        comp._fact_slots(t1)



# ------------------------------------------------------------------ D5

def test_d5_position_after_a_progress_label_supersedes(db):
    """Tes review 6 D5: a position number after a progress label noun is a
    value, not a name. "on episode 5" → "on episode 9" etc. must supersede;
    before the fix the nouns in _IDENTIFIER_LABELS kept the number in the slot
    key, so both facts stayed active."""
    rows = [
        ("The user is on episode 5 of The Crown",
         "The user is on episode 9 of The Crown"),
        ("The user is on page 120 of Dune",
         "The user is on page 310 of Dune"),
        ("The user reached level 30 in Elden Ring",
         "The user reached level 45 in Elden Ring"),
        ("The user is on chapter 4 of the novel",
         "The user is on chapter 11 of the novel"),
        ("The user is watching season 2 of Succession",
         "The user is watching season 3 of Succession"),
        ("The user's daughter is in grade 3",
         "The user's daughter is in grade 4"),
        ("The user finished round 2 of interviews at Google",
         "The user finished round 3 of interviews at Google"),
        ("The user's character is level 12",
         "The user's character is level 20"),
        ("The user is in week 6 of the training plan",
         "The user is in week 9 of the training plan"),
        ("The user's team is in stage 2 of the project",
         "The user's team is in stage 3 of the project"),
    ]
    for older_text, newer_text in rows:
        f1 = _fact(db, older_text,
                   _capture(db, older_text, "2023-05-01T00:00:00+00:00"))
        f2 = _fact(db, newer_text,
                   _capture(db, newer_text, "2023-08-01T00:00:00+00:00"))
        consolidate(db[0], db[1])
        assert _row(db[0], f1)["status"] == "superseded", older_text
        assert _row(db[0], f1)["superseded_by"] == f2, older_text
        assert _row(db[0], f2)["status"] == "active", older_text
        assert _flags(db[0]) == 0, older_text


def test_d5_part_b_position_shapes_supersede(db):
    """Tes review 6 D5 Part B: the three frozen ku_labels6 shapes must
    supersede on a later position; before the fix they keyed apart and both
    stayed active."""
    rows = [
        ("The user is currently on page 200 of A Short History of Nearly Everything",
         "The user is now on page 220 of A Short History of Nearly Everything"),
        ("The user is currently on episode 10 of the Crash Course Science series",
         "The user is currently on episode 50 of the Crash Course Science series"),
        ("The user's goal is to reach level 100 in Apex Legends",
         "The user's goal is to reach level 150 in Apex Legends"),
    ]
    for older_text, newer_text in rows:
        f1 = _fact(db, older_text,
                   _capture(db, older_text, "2023-05-01T00:00:00+00:00"))
        f2 = _fact(db, newer_text,
                   _capture(db, newer_text, "2023-08-01T00:00:00+00:00"))
        consolidate(db[0], db[1])
        assert _row(db[0], f1)["status"] == "superseded", older_text
        assert _row(db[0], f1)["superseded_by"] == f2, older_text
        assert _row(db[0], f2)["status"] == "active", older_text
        assert _flags(db[0]) == 0, older_text


def test_d5_identifier_keying_is_unchanged():
    """Tes review 6 D5: removing the progress nouns must not weaken the
    identifier keying review-6 accepted — these pairs must still key apart."""
    pairs = [
        ("Phase 1 was accepted after correction.",
         "Phase 2 was accepted after correction."),
        ("conv-26 baseline", "conv-30 baseline"),
        ("Cairn at budget 600 scored 91.7% accuracy at 931 tokens",
         "Cairn at budget 1200 scored 91.7% accuracy at 1,613 tokens"),
        ("b600 run", "b1200 run"),
        ("Chapter 2: A League of Extraordinary Talent",
         "Chapter 3: Rising to the Challenge"),
    ]
    for a, b in pairs:
        assert comp._split_subject_slot(a)[0] != comp._split_subject_slot(b)[0], (a, b)
    assert "page" not in comp._IDENTIFIER_LABELS
    assert "episode" not in comp._IDENTIFIER_LABELS
    assert "level" not in comp._IDENTIFIER_LABELS
    assert "chapter" not in comp._IDENTIFIER_LABELS
    assert "season" not in comp._IDENTIFIER_LABELS
    assert "grade" not in comp._IDENTIFIER_LABELS
    assert "round" not in comp._IDENTIFIER_LABELS
    assert "stage" not in comp._IDENTIFIER_LABELS
    assert "step" not in comp._IDENTIFIER_LABELS
    assert "unit" not in comp._IDENTIFIER_LABELS
    assert "volume" not in comp._IDENTIFIER_LABELS
    for kept in ("phase", "conv", "budget", "section", "question"):
        assert kept in comp._IDENTIFIER_LABELS


def test_d5_hyphen_joined_digits_after_an_unlisted_label_stay_in_the_key():
    """Gap G1: digits hyphen-joined to a word stay in the key even when the
    word is not on the label list — "invoice-4471" and "invoice-4472" name
    different invoices and must not supersede."""
    k1 = comp._split_subject_slot("invoice-4471 was paid")[0]
    k2 = comp._split_subject_slot("invoice-4472 was paid")[0]
    assert k1 != k2
    assert "4471" in k1
    assert "4472" in k2


def test_d5_noun_modifier_is_the_only_reason_a_status_word_is_rejected(db):
    """Gap G2: a status word inside a noun modifier ("single-handedly") is not
    a relationship claim; "married" → "single-handedly running the bake sale"
    must not supersede or flag."""
    t1 = "The user is married"
    t2 = "The user is single-handedly running the bake sale"
    f1 = _fact(db, t1, _capture(db, t1, "2023-05-01T00:00:00+00:00"))
    _fact(db, t2, _capture(db, t2, "2023-08-01T00:00:00+00:00"))
    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "active"
    assert _flags(db[0]) == 0
    assert comp._relationship_status_slot(
        "The user is single-handedly running the bake sale") is None

# ------------------------------------------------------------------ P8 harness
#
# Harness tests for the phase-17 rewrite (docs/phase17-brief.md P8): no model
# calls — the answer/extraction endpoint is a stub client, the judge and the
# judge /health identity are monkeypatched, and the embedding endpoint is
# forced offline so retrieve degrades to its lexical path.

import json  # noqa: E402  (the base tests import nothing but pytest/sys)
import os  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "eval"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "eval",
                                "longmemeval"))

import harness  # noqa: E402
import ku_paired  # noqa: E402
import lme_eval as lme  # noqa: E402
from cairnstone import retrieve  # noqa: E402

FROZEN_TEST_SHA = "frozen-test-sha"


class StubClient:
    """Stub client (P8.7): extraction calls (compile_all) get a scripted fact,
    answer calls get a value that reveals which facts reached the brief —
    either a fixed string or, when `resolver` is set, computed from the
    prompt (messages[-1] is the volatile user message carrying the brief)."""

    def __init__(self, answer="Perth", resolver=None):
        self.answer = answer
        self.resolver = resolver
        self.calls = []

    def chat(self, messages, model=None, max_tokens=1024, think=False,
             temperature=0.0):
        self.calls.append(messages)
        if messages and messages[0]["content"] == comp.EXTRACTION_SYSTEM:
            return ('{"facts": [{"text": "Melanie has a dog",'
                    ' "subject": "Melanie",'
                    ' "quote": "Melanie owns a golden retriever",'
                    ' "bucket": "people", "page_title": "Melanie",'
                    ' "page_path": "people/melanie"}]}')
        if self.resolver is not None:
            return self.resolver(messages)
        return self.answer

    def telemetry_last(self):
        return {}

    def extraction_calls(self):
        return sum(1 for c in self.calls
                   if c and c[0]["content"] == comp.EXTRACTION_SYSTEM)


def _offline_embeddings(texts):
    raise RuntimeError("embedding endpoint unavailable in tests")


@pytest.fixture
def ku_env(tmp_path, monkeypatch):
    """Scratch ku-db dir with every endpoint stubbed out."""
    db_dir = tmp_path / "ku-db"
    db_dir.mkdir()
    monkeypatch.setattr(ku_paired, "KU_DB_DIR", db_dir)
    monkeypatch.setattr(retrieve, "_request_embeddings", _offline_embeddings)
    client = StubClient()
    monkeypatch.setattr(lme, "_client", client)
    monkeypatch.setattr(harness, "judge",
                        lambda q, gold, predicted, model=None: (True, False))
    monkeypatch.setattr(ku_paired, "judge_identity", lambda: {
        "name": "stub-judge", "label": "LOCAL-JUDGED",
        "upstream_model": "stub-upstream", "utc": "2026-11-10T00:00:00Z"})
    return db_dir, client


def _write_ids_config(tmp_path, ids, eligible=None):
    ds = tmp_path / "scratch-dataset.json"
    ds.write_text("[]")
    cfg = {
        "frozen_code_sha": FROZEN_TEST_SHA,
        "dataset_path": str(ds),
        "ids": ids,
        "eligible_ids": eligible if eligible is not None else list(ids),
        "budget_tokens": 600,
        "max_mutation_rate": 0.2,
    }
    p = tmp_path / "ids-config.json"
    p.write_text(json.dumps(cfg))
    return p


def _scratch_question(qid, sessions):
    """A minimal KU question: haystack sessions are (date, turns) pairs."""
    return {
        "question_id": qid,
        "question": "What is Caroline's relationship status?",
        "answer": "single",
        "question_type": "knowledge-update",
        "haystack_dates": [s[0] for s in sessions],
        "haystack_sessions": [s[1] for s in sessions],
        "answer_session_ids": [],
    }


def _scratch_brain(db_dir, qid, texts, path="people/caroline"):
    """Hand-built brain: the facts are written directly (bypassing
    compile_all, which would resolve the contradiction at compile time), so
    both are active when the harness reuses the brain. The embedding cache
    table is created and the WAL flushed first, because the harness warms the
    cache before hashing the file for its sidecar — a hand-written sidecar
    must describe the file in the same state a harness-written one would."""
    db_path = db_dir / ("%s.db" % qid)
    conn = store.init_db(str(db_path))
    ws = store.create_workspace(conn, "w")
    brain = store.create_brain(conn, ws, "b", "b")
    fact_ids = []
    for i, text in enumerate(texts):
        cid = _capture((conn, brain), text, "2023-0%d-01T00:00:00+00:00"
                       % (i + 5))
        fact_ids.append(_fact((conn, brain), text, cid, path=path))
    retrieve.ensure_embedding_cache(conn)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return db_path, conn, brain, fact_ids


def _write_sidecar_for(conn, db_path, qid, cfg_path, captures, facts):
    # The hash must be the checkpointed one, exactly as _open_pristine records
    # it: a hash taken with writes still in the WAL can never match on reuse.
    ku_paired.write_sidecar(
        db_path, question_id=qid, code_sha=FROZEN_TEST_SHA,
        config_sha256=ku_paired.sha256_file(cfg_path),
        dataset_sha256=ku_paired.sha256_file(tmp_dataset(cfg_path)),
        summary={"captures": captures, "facts_accepted": facts},
        started_utc="2026-11-10T00:00:00Z",
        db_sha256=ku_paired.checkpointed_sha(conn, db_path))


def _ingest_haystack(db_dir, qid, cfg_path):
    """Put a scratch brain into its post-compile state: ingest the question's
    haystack with the stub client (no facts extracted), so run_one's reuse path
    has nothing left to write. Returns the question used."""
    q = _scratch_question(qid, [
        ("2023/05/01 (Mon) 10:00", [{"role": "user", "content": "hi"}]),
        ("2023/06/01 (Thu) 10:00", [{"role": "user", "content": "hi"}]),
    ])
    import lme_eval as lme  # noqa: PLC0415  (only needed here)
    conn, _, _ = lme.compile_question(q, db_dir / ("%s.db" % qid), StubClient(),
                                      False)
    # Checkpoint before closing: the caller hashes the file next, and a hash
    # taken with writes still in the WAL would not be the on-disk hash.
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return q


def tmp_dataset(cfg_path):
    return json.loads(Path(cfg_path).read_text())["dataset_path"]


# --- P8.8: the fail-closed reuse rule, as one unit-tested function

def test_check_sidecar_happy_path(tmp_path):
    db_path, conn, _, _ = _scratch_brain(tmp_path, "aa11bb22",
                                         ["Caroline is single"])
    cfg = _write_ids_config(tmp_path, ["aa11bb22"])
    ku_paired.write_sidecar(
        db_path, question_id="aa11bb22", code_sha=FROZEN_TEST_SHA,
        config_sha256=ku_paired.sha256_file(cfg),
        dataset_sha256=ku_paired.sha256_file(tmp_dataset(cfg)),
        summary={"captures": 1, "facts_accepted": 1},
        started_utc="2026-11-10T00:00:00Z")
    ok, reason, meta = ku_paired.check_sidecar(
        db_path, FROZEN_TEST_SHA, ku_paired.sha256_file(cfg),
        ku_paired.sha256_file(tmp_dataset(cfg)))
    conn.close()
    assert ok and reason == "sidecar-ok" and meta["question_id"] == "aa11bb22"


def test_check_sidecar_missing(tmp_path):
    db_path = tmp_path / "aa11bb22.db"
    conn = store.init_db(str(db_path))
    ws = store.create_workspace(conn, "w")
    store.create_brain(conn, ws, "b", "b")
    conn.close()
    ok, reason, meta = ku_paired.check_sidecar(db_path, "sha", "csha", "dsha")
    assert not ok and reason == "sidecar-missing" and meta is None


def test_check_sidecar_code_sha_mismatch(tmp_path):
    db_path, conn, _, _ = _scratch_brain(tmp_path, "aa11bb22",
                                         ["Caroline is single"])
    cfg = _write_ids_config(tmp_path, ["aa11bb22"])
    ku_paired.write_sidecar(
        db_path, question_id="aa11bb22", code_sha="pre-freeze-sha",
        config_sha256=ku_paired.sha256_file(cfg),
        dataset_sha256=ku_paired.sha256_file(tmp_dataset(cfg)),
        summary={"captures": 1, "facts_accepted": 1},
        started_utc="2026-11-10T00:00:00Z")
    conn.close()
    ok, reason, _ = ku_paired.check_sidecar(
        db_path, FROZEN_TEST_SHA, ku_paired.sha256_file(cfg),
        ku_paired.sha256_file(tmp_dataset(cfg)))
    assert not ok and reason == "sidecar-mismatch"


def test_check_sidecar_config_sha_mismatch(tmp_path):
    db_path, conn, _, _ = _scratch_brain(tmp_path, "aa11bb22",
                                         ["Caroline is single"])
    cfg = _write_ids_config(tmp_path, ["aa11bb22"])
    ku_paired.write_sidecar(
        db_path, question_id="aa11bb22", code_sha=FROZEN_TEST_SHA,
        config_sha256="stale-config-sha",
        dataset_sha256=ku_paired.sha256_file(tmp_dataset(cfg)),
        summary={"captures": 1, "facts_accepted": 1},
        started_utc="2026-11-10T00:00:00Z")
    conn.close()
    ok, reason, _ = ku_paired.check_sidecar(
        db_path, FROZEN_TEST_SHA, ku_paired.sha256_file(cfg),
        ku_paired.sha256_file(tmp_dataset(cfg)))
    assert not ok and reason == "sidecar-mismatch"


def test_check_sidecar_db_hash_mismatch(tmp_path):
    db_path, conn, _, _ = _scratch_brain(tmp_path, "aa11bb22",
                                         ["Caroline is single"])
    cfg = _write_ids_config(tmp_path, ["aa11bb22"])
    ku_paired.write_sidecar(
        db_path, question_id="aa11bb22", code_sha=FROZEN_TEST_SHA,
        config_sha256=ku_paired.sha256_file(cfg),
        dataset_sha256=ku_paired.sha256_file(tmp_dataset(cfg)),
        summary={"captures": 1, "facts_accepted": 1},
        started_utc="2026-11-10T00:00:00Z")
    # Mutate the brain after the sidecar was written.
    conn.execute("UPDATE facts SET status = 'superseded'")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    ok, reason, _ = ku_paired.check_sidecar(
        db_path, FROZEN_TEST_SHA, ku_paired.sha256_file(cfg),
        ku_paired.sha256_file(tmp_dataset(cfg)))
    assert not ok and reason == "sidecar-mismatch"


def test_check_sidecar_unparseable(tmp_path):
    db_path, conn, _, _ = _scratch_brain(tmp_path, "aa11bb22",
                                         ["Caroline is single"])
    conn.close()
    ku_paired.sidecar_path(db_path).write_text("{not json")
    ok, reason, _ = ku_paired.check_sidecar(db_path, "sha", "csha", "dsha")
    assert not ok and reason == "sidecar-mismatch"


# --- P8.7 item 1: the contradiction test — (a) reads the unconsolidated DB

def test_run_one_arm_a_reads_unconsolidated_brain(ku_env, tmp_path):
    db_dir, client = ku_env
    cfg_path = _write_ids_config(tmp_path, ["aa11bb22"])
    cfg = ku_paired.load_config(str(cfg_path))
    # The brain needs enough facts for the P11 mutation-rate guard: one
    # supersession in a two-fact brain is 50%, over the 20% limit, so the pass
    # would halt and arm (b) would read the same brain as arm (a).
    db_path, conn, brain, fact_ids = _scratch_brain(
        db_dir, "aa11bb22",
        ["Caroline is single", "Caroline is married"]
        # Distinct filler: near-identical filler facts would be linked as
        # duplicates and push the mutation rate over the P11 limit.
        + ["User visited Paris", "User likes jazz", "User speaks French",
           "User drives a Volvo", "User drinks tea", "User plays chess",
           "User grew up in Leeds", "User collects stamps", "User fears heights",
           "User enjoys hiking"])
    # Put the brain into its post-compile state: the question's haystack is
    # ingested first, so run_one's reuse path has nothing left to write. Without
    # this the harness legitimately re-ingests and the sha assertion is testing
    # the test's setup, not the harness.
    _warm = _ingest_haystack(db_dir, "aa11bb22", cfg_path)
    ku_paired.warm_embedding_cache(conn, brain, _warm, 600)
    _write_sidecar_for(conn, db_path, "aa11bb22", cfg_path, 2, 2)
    conn.close()
    # The stub answers from the brief content: the volatile message carries
    # the brief's records, so "single" present means the stale fact was read.
    client.resolver = lambda msgs: ("single" if "single" in msgs[-1]["content"]
                                    else "married")

    q = _scratch_question("aa11bb22", [
        ("2023/05/01 (Mon) 10:00", [{"role": "user", "content": "hi"}]),
        ("2023/06/01 (Thu) 10:00", [{"role": "user", "content": "hi"}]),
    ])
    row = ku_paired.run_one(q, 600, StubClient(), cfg)

    # Arm (a)'s brief was read from the unconsolidated DB: the stub answers
    # from the brief content, and only the pristine brain still carries the
    # stale fact as active.
    assert row["arm_a"]["answer"] == "single"
    assert row["arm_b"]["answer"] == "married"
    # ...and the DBs say the same thing: the stale fact is active in the
    # pristine brain and superseded in the consolidated copy.
    p = store.init_db(str(db_path))
    assert p.execute("SELECT status FROM facts WHERE id = ?",
                     (fact_ids[0],)).fetchone()["status"] == "active"
    p.close()
    c = store.init_db(str(ku_paired.consolidated_path(db_path)))
    assert c.execute("SELECT status FROM facts WHERE id = ?",
                     (fact_ids[0],)).fetchone()["status"] == "superseded"
    c.close()


# --- P8.7 item 2: the pristine sha256 is unchanged after a full run_one

def test_run_one_pristine_sha_unchanged(ku_env, tmp_path):
    db_dir, client = ku_env
    cfg_path = _write_ids_config(tmp_path, ["aa11bb22"])
    cfg = ku_paired.load_config(str(cfg_path))
    db_path, conn, brain, _ = _scratch_brain(db_dir, "aa11bb22",
                                             ["Caroline is single"])
    q = _ingest_haystack(db_dir, "aa11bb22", cfg_path)
    # The harness warms the brief before hashing, so the sidecar must describe
    # the post-warm file. Warming writes retrieval telemetry; a sidecar written
    # before it can never match and every reuse silently recompiles.
    ku_paired.warm_embedding_cache(conn, brain, q, 600)
    _write_sidecar_for(conn, db_path, "aa11bb22", cfg_path, 1, 1)
    conn.close()
    # Checkpoint before hashing, exactly as the harness does: a bare file hash
    # can miss writes still in the WAL.
    _c = store.init_db(str(db_path))
    before = ku_paired.checkpointed_sha(_c, db_path)
    _c.close()

    q = _scratch_question("aa11bb22", [
        ("2023/05/01 (Mon) 10:00", [{"role": "user", "content": "hi"}]),
    ])
    row = ku_paired.run_one(q, 600, StubClient(), cfg)

    assert ku_paired.sha256_file(db_path) == before
    assert row["pristine_db_sha256"] == before


# --- P8.7 item 3: a second run_one reuses when the sidecar matches

def test_second_run_one_reuses_without_recompiling(ku_env, tmp_path):
    db_dir, client = ku_env
    cfg_path = _write_ids_config(tmp_path, ["aa11bb22"])
    cfg = ku_paired.load_config(str(cfg_path))
    q = _scratch_question("aa11bb22", [
        ("2023/05/01 (Mon) 10:00",
         [{"role": "user", "content": "Melanie owns a golden retriever"}]),
        ("2023/06/01 (Thu) 10:00",
         [{"role": "user", "content": "Melanie walked the dog"}]),
    ])
    row1 = ku_paired.run_one(q, 600, client, cfg)
    assert row1["reused"] is False and row1["reuse_reason"] == "db-missing"
    extractions_after_first = client.extraction_calls()
    assert extractions_after_first > 0

    row2 = ku_paired.run_one(q, 600, client, cfg)
    assert row2["reused"] is True and row2["reuse_reason"] == "sidecar-ok"
    assert client.extraction_calls() == extractions_after_first
    assert row2["compile"]["captures"] == row1["compile"]["captures"]
    assert row2["compile"]["facts"] == row1["compile"]["facts"]
    assert row2["pristine_db_sha256"] == row1["pristine_db_sha256"]


# --- P8.7 item 4: a missing sidecar forces a recompile

def test_missing_sidecar_recompiles_and_never_reads_stale_db(ku_env, tmp_path):
    db_dir, client = ku_env
    cfg_path = _write_ids_config(tmp_path, ["aa11bb22"])
    cfg = ku_paired.load_config(str(cfg_path))
    # A stale brain with no sidecar: compile_all would never produce this
    # fact, so its survival would prove the stale DB was read.
    db_path = db_dir / "aa11bb22.db"
    conn = store.init_db(str(db_path))
    ws = store.create_workspace(conn, "w")
    brain = store.create_brain(conn, ws, "b", "b")
    cid = _capture((conn, brain), "stale", "2023-05-01T00:00:00+00:00")
    _fact((conn, brain), "STALE MARKER FACT", cid)
    conn.close()

    q = _scratch_question("aa11bb22", [
        ("2023/05/01 (Mon) 10:00",
         [{"role": "user", "content": "Melanie owns a golden retriever"}]),
        ("2023/06/01 (Thu) 10:00",
         [{"role": "user", "content": "Melanie walked the dog"}]),
    ])
    row = ku_paired.run_one(q, 600, client, cfg)

    assert row["reused"] is False and row["reuse_reason"] == "sidecar-missing"
    # The harness recompiled: the row's counts come from the fresh compile of
    # the question's haystack (2 sessions -> 2 captures), not the stale brain.
    assert row["compile"]["captures"] == 2
    fresh = store.init_db(str(db_path))
    texts = [r["text"] for r in fresh.execute("SELECT text FROM facts")]
    fresh.close()
    assert "STALE MARKER FACT" not in texts


# --- P8.7 item 5: a mismatched sidecar is refused the same way

def test_mismatched_sidecar_recompiles_and_never_reads_stale_db(ku_env,
                                                                tmp_path):
    db_dir, client = ku_env
    cfg_path = _write_ids_config(tmp_path, ["aa11bb22"])
    cfg = ku_paired.load_config(str(cfg_path))
    db_path, conn, _, _ = _scratch_brain(db_dir, "aa11bb22",
                                         ["STALE MARKER FACT"])
    # Sidecar from pre-freeze code: wrong code_sha, everything else valid.
    ku_paired.write_sidecar(
        db_path, question_id="aa11bb22", code_sha="pre-freeze-sha",
        config_sha256=cfg["_config_sha256"],
        dataset_sha256=cfg["_dataset_sha256"],
        summary={"captures": 1, "facts_accepted": 1},
        started_utc="2026-11-10T00:00:00Z")
    conn.close()

    q = _scratch_question("aa11bb22", [
        ("2023/05/01 (Mon) 10:00",
         [{"role": "user", "content": "Melanie owns a golden retriever"}]),
        ("2023/06/01 (Thu) 10:00",
         [{"role": "user", "content": "Melanie walked the dog"}]),
    ])
    row = ku_paired.run_one(q, 600, client, cfg)

    assert row["reused"] is False and row["reuse_reason"] == "sidecar-mismatch"
    fresh = store.init_db(str(db_path))
    texts = [r["text"] for r in fresh.execute("SELECT text FROM facts")]
    fresh.close()
    assert "STALE MARKER FACT" not in texts


# --- P8.7 item 6: the consolidation call receives max_mutation_rate=0.2

def test_consolidate_receives_max_mutation_rate(ku_env, tmp_path, monkeypatch):
    db_dir, client = ku_env
    cfg_path = _write_ids_config(tmp_path, ["aa11bb22"])
    cfg = ku_paired.load_config(str(cfg_path))
    db_path, conn, _, _ = _scratch_brain(db_dir, "aa11bb22",
                                         ["Caroline is single"])
    _write_sidecar_for(conn, db_path, "aa11bb22", cfg_path, 1, 1)
    conn.close()

    seen = []

    def fake_consolidate(conn, brain_id, max_mutation_rate=None):
        seen.append(max_mutation_rate)
        return {"superseded": 0, "duplicates_linked": 0, "flagged": 0}

    monkeypatch.setattr(comp, "consolidate", fake_consolidate)

    q = _scratch_question("aa11bb22", [
        ("2023/05/01 (Mon) 10:00", [{"role": "user", "content": "hi"}]),
    ])
    ku_paired.run_one(q, 600, StubClient(), cfg)
    assert seen == [0.2]


# --- P8.8: the consolidated copy's sidecar — source-hash rule

def test_consolidated_copy_rebuilt_when_source_hash_differs(ku_env, tmp_path,
                                                            monkeypatch):
    db_dir, client = ku_env
    cfg_path = _write_ids_config(tmp_path, ["aa11bb22"])
    cfg = ku_paired.load_config(str(cfg_path))
    db_path, conn, _, _ = _scratch_brain(db_dir, "aa11bb22",
                                         ["Caroline is single"])
    _write_sidecar_for(conn, db_path, "aa11bb22", cfg_path, 1, 1)
    conn.close()

    calls = []

    def fake_consolidate(conn, brain_id, max_mutation_rate=None):
        calls.append(max_mutation_rate)
        return {"superseded": 0, "duplicates_linked": 0, "flagged": 0}

    monkeypatch.setattr(comp, "consolidate", fake_consolidate)

    q = _scratch_question("aa11bb22", [
        ("2023/05/01 (Mon) 10:00", [{"role": "user", "content": "hi"}]),
    ])
    ku_paired.run_one(q, 600, StubClient(), cfg)
    assert len(calls) == 1

    # Forge the copy's sidecar so it claims derivation from a different
    # pristine brain: the copy must be rebuilt, not reused.
    cons_path = ku_paired.consolidated_path(db_path)
    meta = json.loads(cons_path.with_suffix(".meta.json").read_text())
    meta["source_db_sha256"] = "0" * 64
    cons_path.with_suffix(".meta.json").write_text(json.dumps(meta))

    ku_paired.run_one(q, 600, StubClient(), cfg)
    assert len(calls) == 2
    rebuilt = json.loads(cons_path.with_suffix(".meta.json").read_text())
    assert rebuilt["source_db_sha256"] == ku_paired.sha256_file(db_path)


# --- P8.6: the judge /health identity is recorded per question

def test_judge_identity_recorded_and_label_change_stops_run(ku_env, tmp_path,
                                                            monkeypatch):
    db_dir, client = ku_env
    cfg_path = _write_ids_config(tmp_path, ["aa11bb22"])
    cfg = ku_paired.load_config(str(cfg_path))
    db_path, conn, _, _ = _scratch_brain(db_dir, "aa11bb22",
                                         ["Caroline is single"])
    _write_sidecar_for(conn, db_path, "aa11bb22", cfg_path, 1, 1)
    conn.close()
    q = _scratch_question("aa11bb22", [
        ("2023/05/01 (Mon) 10:00", [{"role": "user", "content": "hi"}]),
    ])

    row = ku_paired.run_one(q, 600, StubClient(), cfg,
                            start_label="LOCAL-JUDGED")
    assert row["judge_identity"]["label"] == "LOCAL-JUDGED"
    assert row["judge_identity"]["name"] == "stub-judge"
    assert row["judge_identity"]["upstream_model"] == "stub-upstream"

    monkeypatch.setattr(ku_paired, "judge_identity", lambda: {
        "name": "stub-judge", "label": "SOMEONE-ELSE",
        "upstream_model": "stub-upstream", "utc": "2026-11-10T00:00:00Z"})
    with pytest.raises(RuntimeError, match="judge label changed"):
        ku_paired.run_one(q, 600, StubClient(), cfg,
                          start_label="LOCAL-JUDGED")


# --- P8.5 / P11: config-driven selection, fail-closed on disagreement

def test_load_config_fails_closed_on_eligible_disagreement(tmp_path):
    pool = [{"question_id": "aa11bb22", "question_type": "knowledge-update"},
            {"question_id": "cc33dd44", "question_type": "knowledge-update"},
            {"question_id": "other", "question_type": "multi-session"}]
    cfg_path = _write_ids_config(tmp_path, ["aa11bb22"],
                                 eligible=["aa11bb22", "zz999999"])
    with pytest.raises(ValueError, match="disagree"):
        ku_paired.load_config(str(cfg_path), pool)


def test_load_config_rejects_ids_outside_eligible(tmp_path):
    pool = [{"question_id": "aa11bb22", "question_type": "knowledge-update"}]
    cfg_path = _write_ids_config(tmp_path, ["aa11bb22", "zz999999"],
                                 eligible=["aa11bb22"])
    with pytest.raises(ValueError, match="outside the eligible set"):
        ku_paired.load_config(str(cfg_path), pool)


def test_load_config_rejects_duplicate_ids(tmp_path):
    cfg_path = _write_ids_config(tmp_path, ["aa11bb22", "aa11bb22"])
    with pytest.raises(ValueError, match="duplicates"):
        ku_paired.load_config(str(cfg_path))


# --- B2 (d): relevance first, then recency

def _recency_question():
    """Five sessions, all overlapping the question; scores fall with session
    length so the relevance order is 0,1,2,3,4 while the recency order of the
    top-4 is 3,1,2,0 — arm (d) must drop the best-scoring session in favour
    of a newer one."""
    sessions = [
        ("2023/01/01 (Sun) 10:00", "alpha beta"),
        ("2023/03/01 (Wed) 10:00", "alpha beta gamma"),
        ("2023/02/01 (Wed) 10:00", "alpha beta delta epsilon"),
        ("2023/04/01 (Sat) 10:00", "alpha beta zeta eta theta"),
        ("2023/05/01 (Mon) 10:00", "alpha beta iota kappa lambda mu"),
    ]
    return {
        "question_id": "dd44ee55",
        "question": "alpha beta",
        "answer": "x",
        "haystack_dates": [s[0] for s in sessions],
        "haystack_sessions": [[{"role": "user", "content": s[1]}]
                              for s in sessions],
    }


def test_keyword_relevance_recency_orders_by_date_keeps_three(monkeypatch):
    monkeypatch.setattr(lme, "_client", StubClient())
    q = _recency_question()
    result = lme.keyword_relevance_recency_backend(q)
    # Top-4 by relevance: 0,1,2,3; ordered by full timestamp descending:
    # 3 (04-01), 1 (03-01), 2 (02-01), 0 (01-01); keep 3.
    assert result["sessions_used"] == [3, 1, 2]


def test_keyword_relevance_recency_unparseable_date_last(monkeypatch):
    monkeypatch.setattr(lme, "_client", StubClient())
    q = _recency_question()
    q["haystack_dates"][3] = "unknown"  # newest session, unparseable
    result = lme.keyword_relevance_recency_backend(q)
    # Top-4 still 0,1,2,3; the unparseable session sorts last, so the kept
    # three are the parseable ones in recency order — the newest session is
    # dropped exactly because its date cannot be parsed.
    assert result["sessions_used"] == [1, 2, 0]


def test_arm_d_score_matches_keyword_backend(monkeypatch):
    """(d) must score sessions with exactly (c)'s score and tokeniser."""
    monkeypatch.setattr(lme, "_client", StubClient())
    q = _recency_question()
    from p17_recall_check import scored_sessions
    scored = scored_sessions(q)
    c_top3 = [si for _, si in scored[:3]]
    assert lme.keyword_backend(q)["sessions_used"] == c_top3

