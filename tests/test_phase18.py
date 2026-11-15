"""Phase 18 regression tests (docs/phase18-brief.md B3): the five knowledge-
update pairs from the real corpus, each failing before the fix and passing
after, plus the negatives that must stay active.

Each pair test builds a brain with the two corpus facts at their real pages,
runs the consolidation pass, and asserts the older fact was superseded. The
mutant proofs (disabling the qty slot, restoring page scope, dropping the
verb groups) are run out of band and recorded in reports/phase18-report.md.
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
    conn = store.init_db(str(tmp_path / "phase18.db"))
    ws = store.create_workspace(conn, "w")
    brain = store.create_brain(conn, ws, "b", "b")
    yield conn, brain
    conn.close()


def _fact(db, text, capture_id, path, title):
    conn, brain = db
    page = conn.execute(
        "SELECT id FROM pages WHERE brain_id = ? AND path = ?",
        (brain, path)).fetchone()
    if page is None:
        bucket = path.split("/")[0]
        page_id = store.create_page(conn, brain, path, bucket, title,
                                    body_md="")
    else:
        page_id = page["id"]
    version_id = conn.execute(
        "SELECT current_version_id FROM pages WHERE id = ?",
        (page_id,)).fetchone()[0]
    content = store.get_capture(conn, capture_id)["content"]
    return store.add_fact(conn, page_id, version_id, text, capture_id,
                          0, max(1, len(content.strip())))


def _capture(db, text, captured_at):
    conn, brain = db
    return store.add_capture(conn, brain, "conversation", text, "src",
                             captured_at=captured_at)


def _row(conn, fact_id):
    return conn.execute("SELECT * FROM facts WHERE id = ?",
                        (fact_id,)).fetchone()


def _pair(db, older, newer):
    """Write an older and a newer fact (a month apart) and return the fact ids."""
    c1 = _capture(db, older[1], "2023-05-01T00:00:00+00:00")
    c2 = _capture(db, newer[1], "2023-06-01T00:00:00+00:00")
    f1 = _fact(db, older[1], c1, older[0], older[0].split("/")[1])
    f2 = _fact(db, newer[1], c2, newer[0], newer[0].split("/")[1])
    return f1, f2


# ---------------------------------------------------------------- B3 pairs
#
# Real corpus texts (fact ids from the ku-db sidecars): Emma 45dc21b6,
# H&M 4b24c848, Yoga 945e3d21, Luna e61a7584, Dr Smith 2698e78f_abs.

def test_b3_emma_number_word_count_supersedes(db):
    """Emma (45dc21b6): "two of Emma's recipes" -> "3 of Emma's recipes".
    Requires A1 (count slot) and A2 (number-word normalisation)."""
    f1, f2 = _pair(db,
                   ("people/emma",
                    "The user has tried two of Emma's recipes from Emma's "
                    "channel"),
                   ("people/emma",
                    "The user has tried 3 of Emma's recipes"))
    result = consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "superseded"
    assert _row(db[0], f2)["status"] == "active"
    assert result["superseded"] == 1, result


def test_b3_hm_possession_paraphrase_across_pages_supersedes(db):
    """H&M (4b24c848): "bought three tops" (people/user) -> "already owns five
    tops" (misc/user). Requires A3 (possession verb group) and A4 (entity
    scope) together."""
    f1, f2 = _pair(db,
                   ("people/user", "The user bought three tops from H&M"),
                   ("misc/user",
                    "User already owns five tops from H&M and is thinking of "
                    "getting a few more"))
    result = consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "superseded"
    assert _row(db[0], f2)["status"] == "active"
    assert result["superseded"] == 1, result


def test_b3_yoga_frequency_across_pages_supersedes(db):
    """Yoga (945e3d21): "does yoga twice a week" (misc/user) -> "attends yoga
    classes three times a week" (people/user). Requires A1 (frequency slot)
    and A4 (entity scope)."""
    f1, f2 = _pair(db,
                   ("misc/user", "The user does yoga twice a week"),
                   ("people/user",
                    "The user attends yoga classes three times a week, which "
                    "helps them stay focused"))
    result = consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "superseded"
    assert _row(db[0], f2)["status"] == "active"
    assert result["superseded"] == 1, result


def test_b3_luna_duration_supersedes(db):
    """Luna (e61a7584): "with her owner for about 6 months" -> "has had Luna
    for about 9 months". Requires A1 (duration slot in days) and A3 (the
    possession group recognises has/had as verbs)."""
    f1, f2 = _pair(db,
                   ("people/luna",
                    "Luna has been with her owner for about 6 months as of "
                    "2023-08-11"),
                   ("people/luna",
                    "The user has had Luna for about 9 months as of "
                    "2023-11-30"))
    result = consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "superseded"
    assert _row(db[0], f2)["status"] == "active"
    assert result["superseded"] == 1, result


def test_b3_dr_smith_frequency_supersedes(db):
    """Dr Smith (2698e78f_abs): "therapy session with Dr. Smith every two
    weeks" -> "sees Dr. Smith every week". Requires A1 (every-N frequency
    normalised to a per-week rate)."""
    f1, f2 = _pair(db,
                   ("people/dr-smith",
                    "User has a therapy session with Dr. Smith every two "
                    "weeks"),
                   ("people/dr-smith",
                    "The user sees Dr. Smith every week"))
    result = consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "superseded"
    assert _row(db[0], f2)["status"] == "active"
    assert result["superseded"] == 1, result


# -------------------------------------------------------------- negatives

def test_b3_alpha_and_beta_ci_facts_stay_active(db):
    """Negative: CI facts on projects/alpha and projects/beta name different
    entities — entity scope (A4) keeps them apart, so neither is superseded
    and nothing is flagged."""
    f1, f2 = _pair(db,
                   ("projects/alpha",
                    "The first CI run failed on 2023-05-01"),
                   ("projects/beta",
                    "The first CI run failed on 2023-05-02"))
    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"


def test_b3_tops_and_books_counts_stay_active(db):
    """Negative: "bought 3 tops from H&M" and "bought 5 books" are counts of
    different objects — the attribute component keeps the slot keys apart, so
    both stay active."""
    f1, f2 = _pair(db,
                   ("people/user", "The user bought 3 tops from H&M"),
                   ("people/user", "The user bought 5 books"))
    result = consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"
    assert result["superseded"] == 0 and result["flagged"] == 0, result


# ------------------------------------------------------- unit views (A1-A4)

def test_b3_quantity_slot_key_shapes():
    """Unit view of the A1 key shapes and A2 normalisation."""
    assert comp._quantity_slots(
        "The user has tried two of Emma's recipes") == [
        ("cat:qty:user:recipe:count", "2")]
    assert comp._quantity_slots(
        "Luna has been with her owner for about 6 months") == [
        ("cat:qty:luna:luna:day", "180")]
    assert comp._quantity_slots("The user does yoga twice a week") == [
        ("cat:qty:yoga:yoga:per_week", "2")]
    assert comp._quantity_slots(
        "User has a therapy session with Dr. Smith every two weeks") == [
        ("cat:qty:smith:smith:per_week", "0.5")]


def test_b3_page_entity_resolution():
    """Unit view of A4: the entity a page names."""
    assert comp._page_entity("misc/user") == "user"
    assert comp._page_entity("misc/the-user") == "user"
    assert comp._page_entity("people/user") == "user"
    assert comp._page_entity("decisions/user") == "user"
    assert comp._page_entity("projects/alpha") != \
        comp._page_entity("projects/beta")


def test_b3_verb_equivalence_groups_documented():
    """Unit view of A3: the documented groups are small and explicit."""
    assert comp._VERB_GROUPS["possession"] == frozenset(
        "own have bought purchased got".split())
    assert comp._VERB_GROUPS["meeting"] == frozenset(
        "see attend visit had a session with".split())
    assert comp._VERB_GROUPS["recipe"] == frozenset(
        "tried tasted made".split())


# ------------------------------------------------- rev 3 precision (rules 1-7)
#
# The five false-positive pairs measured in docs/phase18-tighten.md: the two
# facts assert different attributes, not competing values for one attribute,
# so neither may supersede or flag the other.

_FALSE_POSITIVE_PAIRS = [
    ("TensorFold cold prefill processes 4,588 tokens in 9.19 s (~500 tok/s)",
     "TensorFold caches 0 tokens for a single concatenated user message with "
     "a changed question"),
    ("The harness had no cap on question count; a 3-sample run is ~600 "
     "questions and takes hours.",
     "The naive_rag eval run on 1 sample with 12 questions wrote results to "
     "eval/results/2026-11-05-naive_rag.json in 22.3 seconds"),
    ("The full_context backend scored 83.3% accuracy at 15,043 tokens.",
     "The naive_rag backend scored 66.7% accuracy at 770 tokens."),
    ("The full_context backend scored 83.3% accuracy with mean 15,043 "
     "context tokens, 3.15 s mean latency, and 91.7% cache hit.",
     "The naive_rag backend scored 66.7% accuracy with mean 770 context "
     "tokens, 2.38 s mean latency, and 0% cache hit."),
    ("Day 2 of the Dubai trip (April 23, 2023) includes Jumeirah Beach "
     "(25.231768, 55.261291), Karak House breakfast (25.229095, 55.261578), "
     "Mall of the Emirates (25.118252, 55.200372), Al Fahidi Historical "
     "Neighborhood (25.264225, 55.299586), and dinner at Al Fanar Restaurant "
     "(25.227604, 55.277908)",
     "Day 3 of the Dubai trip (April 24, 2023) includes Global Village "
     "(25.072927, 55.308932), JBR The Beach (25.081542, 55.134379), lunch at "
     "Automatic Restaurant (25.082405, 55.139757), Souk Madinat Jumeirah "
     "(25.133796, 55.183401), and dinner at Al Ibrahimi (25.137567, "
     "55.188116)"),
]


@pytest.mark.parametrize("older,newer", _FALSE_POSITIVE_PAIRS)
def test_rev3_false_positive_pairs_produce_no_flag(db, older, newer):
    """Rules 1-3: measurement/prepositional numbers, non-counting verbs and
    day/ordinal numbers form no quantity slot, so the pair never collides."""
    f1, f2 = _pair(db, ("misc/user", older), ("misc/user", newer))
    result = consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"
    assert result["superseded"] == 0 and result["flagged"] == 0, result


@pytest.mark.parametrize("text", [
    "Day 2 of the Dubai trip (April 23, 2023) includes Jumeirah Beach",
    "Day 3 of the Dubai trip (April 24, 2023) includes Global Village",
    "Phase 11 is mid-flight as of 2026-11-05",
    "The full_context backend scored 83.3% accuracy at 15,043 tokens.",
    "The naive_rag eval run on 1 sample with 12 questions",
])
def test_rev3_no_quantity_slot_for_ordinals_labels_and_pp_numbers(text):
    """Rules 1 and 3: day/ordinal/label numbers and numbers inside
    prepositional phrases form no quantity slot at all."""
    assert comp._quantity_slots(text) == []


def test_rev3_counting_verb_required(db):
    """Rule 2: a number governed by a verb outside the closed counting set
    ("caches 0 tokens" vs "processes 4,588 tokens") forms no count slot, so
    the two TensorFold facts never collide."""
    assert comp._quantity_slots(
        "TensorFold cold prefill processes 4,588 tokens in 9.19 s") == []
    assert comp._quantity_slots(
        "TensorFold caches 0 tokens for a single concatenated user message") \
        == []


def test_rev3_one_quantity_slot_per_fact():
    """Rule 7: a fact asserting several quantities keys on the first one and
    emits no extra slots for incidental numbers."""
    assert comp._quantity_slots(
        "The user bought 3 tops and 2 hats from H&M") == [
        ("cat:qty:user:top:count", "3")]
    assert comp._quantity_slots(
        "The user has had Luna for about 9 months and 2 vet visits") == [
        ("cat:qty:luna:luna:day", "270")]


# ------------------------------------------------- rev 4: specification numerals
#
# Measured on 85fa3a3f.db: "Average cost for a 5 kW solar system ..." was
# superseded by "Average cost for a 10 kW solar system ..." — different
# specifications, not an update. A number attached to a unit of measure and
# followed by a noun stays in the key, so the two claims cannot collide.

def test_rev4_specification_numerals_do_not_supersede(db):
    f1, f2 = _pair(db,
                   ("misc/user", "Average cost for a 5 kW solar system in "
                    "California is $12,500 to $17,500"),
                   ("misc/user", "Average cost for a 10 kW solar system in "
                    "California is $25,000 to $35,000"))
    consolidate(db[0], db[1])
    assert _row(db[0], f1)["status"] == "active"
    assert _row(db[0], f2)["status"] == "active"


def test_rev4_trailing_measurement_is_still_a_value(db):
    """\"ran 5 km\" -> \"ran 10 km\" is a value change, not a specification:
    no noun follows the unit, so the number stays a value and the pair
    supersedes (phase 17 D1 expects value ('5',))."""
    assert comp._split_subject_slot("The user ran 5 km")[1] == ("5",)
    assert comp._split_subject_slot("The user ran 10 km")[1] == ("10",)
    assert (comp._split_subject_slot("The user ran 5 km")[0]
            == comp._split_subject_slot("The user ran 10 km")[0])
