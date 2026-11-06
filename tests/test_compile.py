"""Offline tests for the phase 2 compile pipeline (no network)."""

import pytest

from cairnstone import store
from cairnstone.compile import (ExtractError, compile_all, dedupe, extract, locate,
                           supersede_contradictions, uncited_facts, upsert_page,
                           write_facts)
from cairnstone.llm import LLMError


class FakeClient:
    """Scripted client: pops one reply per chat() call, records messages."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, model=None, max_tokens=1024, think=False,
             temperature=0.0):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


FACT_JSON = ('{"facts": [{"text": "Caroline is a transgender woman",'
             ' "subject": "Caroline",'
             ' "quote": "I am a transgender woman",'
             ' "bucket": "people", "page_title": "Caroline",'
             ' "page_path": "people/caroline"}]}')


@pytest.fixture
def db(tmp_path):
    conn = store.init_db(str(tmp_path / "test.db"))
    ws = store.create_workspace(conn, "w")
    brain = store.create_brain(conn, ws, "b", "b")
    yield conn, brain


CAPTURE = ("Caroline: Hi Mel. I am a transgender woman and I started "
           "hormones in March. Melanie: That's big news!")


def _capture(db, text=CAPTURE):
    conn, brain = db
    return store.add_capture(conn, brain, "conversation", text, "test:1")


# 1. quote absent -> rejected
def test_absent_quote_rejected(db):
    conn, brain = db
    cid = _capture(db)
    client = FakeClient(['{"facts": [{"text": "Melanie has a dog",'
                         ' "subject": "Melanie",'
                         ' "quote": "Melanie owns a golden retriever",'
                         ' "bucket": "people", "page_title": "Melanie",'
                         ' "page_path": "people/melanie"}]}'])
    result = compile_all(conn, brain, [cid], client)
    assert result["facts_accepted"] == 0
    assert len(result["facts_rejected"]) == 1
    assert "quote not found" in result["facts_rejected"][0][2]


# 2. valid fact -> correct span
def test_valid_fact_span(db):
    conn, brain = db
    cid = _capture(db)
    client = FakeClient([FACT_JSON])
    result = compile_all(conn, brain, [cid], client)
    assert result["facts_accepted"] == 1
    fact = store.facts_for_page(conn, 1)[0]
    assert CAPTURE[fact["span_start"]:fact["span_end"]] == "I am a transgender woman"
    assert fact["quote"] == "I am a transgender woman"


# 3. invalid JSON -> one retry then recorded failure
def test_invalid_json_retry_then_failure(db):
    conn, brain = db
    cid = _capture(db)
    client = FakeClient(["not json at all", "still not json"])
    with pytest.raises(ExtractError):
        extract(CAPTURE, client)
    assert len(client.calls) == 2  # exactly one retry
    # And through the pipeline it becomes a failed capture, not a crash.
    client2 = FakeClient(["bad", "worse"])
    result = compile_all(conn, brain, [cid], client2)
    assert result["failed_captures"] == [cid]
    assert result["facts_accepted"] == 0


def test_retry_succeeds_on_second_try(db):
    conn, brain = db
    cid = _capture(db)
    client = FakeClient(["oops {", FACT_JSON])
    facts = extract(CAPTURE, client)
    assert len(facts) == 1
    client2 = FakeClient([FACT_JSON])
    result = compile_all(conn, brain, [cid], client2)
    assert result["facts_accepted"] == 1


# 4. duplicate facts are not duplicated
def test_duplicates_not_duplicated(db):
    conn, brain = db
    cid = _capture(db)
    cid2 = store.add_capture(conn, brain, "conversation",
                             "Caroline: Again, I am a transgender woman.", "test:2")
    client = FakeClient([FACT_JSON, FACT_JSON])
    result = compile_all(conn, brain, [cid, cid2], client)
    assert result["facts_accepted"] == 2
    assert result["duplicates_linked"] == 1
    page = store.get_page(conn, "people/caroline")["page"]
    active = store.facts_for_page(conn, page["id"], status="active")
    assert len(active) == 1


# 5. contradictory dates -> supersede, old fact still present
def test_contradiction_superseded(db):
    conn, brain = db
    text1 = "Caroline: I started hormones in March."
    text2 = "Caroline: I started hormones in April."
    cid1 = store.add_capture(conn, brain, "conversation", text1, "test:1")
    cid2 = store.add_capture(conn, brain, "conversation", text2, "test:2")
    f1 = ('{"facts": [{"text": "Caroline started hormones in March",'
          ' "subject": "Caroline",'
          ' "quote": "I started hormones in March", "bucket": "decisions",'
          ' "page_title": "Hormones", "page_path": "decisions/hormones"}]}')
    f2 = ('{"facts": [{"text": "Caroline started hormones in April",'
          ' "subject": "Caroline",'
          ' "quote": "I started hormones in April", "bucket": "decisions",'
          ' "page_title": "Hormones", "page_path": "decisions/hormones"}]}')
    client = FakeClient([f1, f2])
    result = compile_all(conn, brain, [cid1, cid2], client)
    assert result["superseded"] == 1
    page = store.get_page(conn, "decisions/hormones")["page"]
    facts = store.facts_for_page(conn, page["id"])
    assert len(facts) == 2  # history kept, never deleted
    active = [f for f in facts if f["status"] == "active"]
    assert len(active) == 1
    assert "April" in active[0]["text"]
    old = [f for f in facts if f["status"] == "superseded"][0]
    assert old["superseded_by"] == active[0]["id"]


# 6. every written fact has a non-empty quote
def test_every_fact_has_quote(db):
    conn, brain = db
    cid = _capture(db)
    client = FakeClient([FACT_JSON])
    compile_all(conn, brain, [cid], client)
    page = store.get_page(conn, "people/caroline")["page"]
    for f in store.facts_for_page(conn, page["id"]):
        assert f["quote"].strip()


# locate unit tests
def test_locate_exact():
    text = "abc def ghi"
    assert locate(text, "def") == (4, 7)
    assert locate(text, "missing") is None
    assert locate(text, "") is None


def test_locate_whitespace_normalised_maps_to_real_offsets():
    text = "I am  a\ntransgender   woman today"
    quote = "I am a transgender woman"
    span = locate(text, quote)
    assert span is not None
    assert text[span[0]:span[1]] == "I am  a\ntransgender   woman"


# upsert_page reuses existing path
def test_upsert_page_reuses(db):
    conn, brain = db
    p1 = upsert_page(conn, brain, "people", "Caroline", "people/caroline")
    p2 = upsert_page(conn, brain, "people", "Caroline", "people/caroline")
    assert p1 == p2


# write_facts via store.add_fact raises on bad version (guard)
def test_write_facts_rejects_store_error(db):
    conn, brain = db
    cid = _capture(db)
    page = upsert_page(conn, brain, "people", "Caroline", "people/caroline")
    facts = [{"text": "Caroline is a transgender woman", "subject": "Caroline",
              "quote": "I am a transgender woman",
              "bucket": "people", "page_title": "Caroline",
              "page_path": "people/caroline"}]
    accepted, rejected = write_facts(conn, page, 9999, cid, facts)
    assert accepted == []
    assert len(rejected) == 1


# ---- added on the maintainer's independent review of phase 2: date resolution, corroboration
# ---- semantics, contradiction precision, and JSON fence tolerance.

def test_extraction_receives_capture_timestamp():
    client = FakeClient([FACT_JSON])
    extract(CAPTURE, client, captured_at="2023-05-07T14:30:00Z")
    assert "Capture timestamp: 2023-05-07T14:30:00Z" in client.calls[0][1]["content"]
    # the timestamp must NOT be inside the text the quote has to match
    assert client.calls[0][1]["content"].endswith(CAPTURE)


def test_relative_date_instruction_present():
    from cairnstone.compile import EXTRACTION_SYSTEM
    assert "absolute date" in EXTRACTION_SYSTEM
    assert "YYYY-MM-DD" in EXTRACTION_SYSTEM


def test_atomic_attribute_rule_forbids_third_party_attribution():
    """Phase 6: the extractor attributed 'You'll be an awesome mom' (spoken TO the
    interlocutor) to Melanie. The rule must restrict attributes to the page subject."""
    from cairnstone.compile import EXTRACTION_SYSTEM
    assert "the subject of the page" in EXTRACTION_SYSTEM
    assert "LISTENER" in EXTRACTION_SYSTEM
    # The over-inference example must not be the only guidance: the restriction
    # against second-person address must be stated explicitly.
    assert "never attribute it to the subject" in EXTRACTION_SYSTEM


def test_code_fenced_json_is_parsed():
    client = FakeClient(["```json\n" + FACT_JSON + "\n```"])
    facts = extract(CAPTURE, client)
    assert len(facts) == 1 and facts[0]["page_path"] == "people/caroline"


def test_dedupe_links_not_retracts(db):
    conn, brain = db
    cid = _capture(db)
    cid2 = store.add_capture(conn, brain, "conversation",
                             "Caroline: Again, I am a transgender woman.", "test:2")
    client = FakeClient([FACT_JSON, FACT_JSON])
    compile_all(conn, brain, [cid, cid2], client)
    page = store.get_page(conn, "people/caroline")["page"]
    all_facts = store.facts_for_page(conn, page["id"], include_duplicates=True)
    assert len(all_facts) == 2
    assert all(f["status"] == "active" for f in all_facts), "duplicates stay active"
    dup = [f for f in all_facts if f["duplicate_of"] is not None]
    assert len(dup) == 1
    canonical = [f for f in all_facts if f["duplicate_of"] is None]
    assert dup[0]["duplicate_of"] == canonical[0]["id"]


def test_different_slots_are_not_contradictions(db):
    conn, brain = db
    cid1 = store.add_capture(conn, brain, "conversation", "Alice: I have 2 cats.", "test:1")
    cid2 = store.add_capture(conn, brain, "conversation", "Alice: I have 3 dogs.", "test:2")
    f1 = ('{"facts": [{"text": "Alice has 2 cats", "subject": "Alice",'
          ' "quote": "I have 2 cats",'
          ' "bucket": "people", "page_title": "Alice", "page_path": "people/alice"}]}')
    f2 = ('{"facts": [{"text": "Alice has 3 dogs", "subject": "Alice",'
          ' "quote": "I have 3 dogs",'
          ' "bucket": "people", "page_title": "Alice", "page_path": "people/alice"}]}')
    result = compile_all(conn, brain, [cid1, cid2], FakeClient([f1, f2]))
    assert result["facts_accepted"] == 2
    assert result["superseded"] == 0, "different slots must not supersede"


def test_month_day_contradiction_detected(db):
    from cairnstone.compile import _split_subject_slot
    k1, v1 = _split_subject_slot("Billing v2 ships Mar 31")
    k2, v2 = _split_subject_slot("Billing v2 ships Apr 30")
    assert k1 == k2, "same slot despite different dates"
    assert v1 != v2


def test_export_excludes_duplicates(db, tmp_path):
    conn, brain = db
    cid = _capture(db)
    cid2 = store.add_capture(conn, brain, "conversation",
                             "Caroline: Again, I am a transgender woman.", "test:2")
    compile_all(conn, brain, [cid, cid2], FakeClient([FACT_JSON, FACT_JSON]))
    out = tmp_path / "export"
    store.export_markdown(conn, brain, str(out))
    text = (out / "people" / "caroline.md").read_text()
    assert text.count("- Caroline is a transgender woman") == 1


# ---- Phase 5B: atomic attribute facts for people ----

ATOMIC_CAPTURE = (
    "Caroline: I plan to become a single parent next year, and I've moved to "
    "Austin for the new nursing job. Melanie: That's a big change!")

ATOMIC_JSON = ('{"facts": ['
               ' {"text": "Caroline is single", "subject": "Caroline",'
               '  "quote": "I plan to become a single parent",'
               '  "bucket": "people", "page_title": "Caroline", "page_path": "people/caroline"},'
               ' {"text": "Caroline lives in Austin", "subject": "Caroline",'
               '  "quote": "moved to Austin",'
               '  "bucket": "people", "page_title": "Caroline", "page_path": "people/caroline"},'
               ' {"text": "Caroline is a nurse", "subject": "Caroline",'
               '  "quote": "new nursing job",'
               '  "bucket": "people", "page_title": "Caroline", "page_path": "people/caroline"}'
               ']}')


def test_atomic_attribute_instruction_present():
    from cairnstone.compile import EXTRACTION_SYSTEM
    for attr in ("relationship status", "location", "occupation", "age",
                 "family role"):
        assert attr in EXTRACTION_SYSTEM, "missing atomic attribute rule: " + attr
    assert "never invent" in EXTRACTION_SYSTEM


def test_atomic_attribute_facts_compile_with_citations(db):
    """The phase-4 gap: 'plans to become a single parent' must yield an atomic
    'Caroline is single' fact, and every emitted fact must cite a locatable quote."""
    conn, brain = db
    cid = store.add_capture(conn, brain, "conversation", ATOMIC_CAPTURE, "test:2")
    facts = extract(ATOMIC_CAPTURE, FakeClient([ATOMIC_JSON]))
    kinds = [f["text"] for f in facts]
    assert any("single" in t for t in kinds), "relationship status fact missing"
    assert any("Austin" in t for t in kinds), "location fact missing"
    assert any("nurse" in t for t in kinds), "occupation fact missing"
    result = compile_all(conn, brain, [cid], FakeClient([ATOMIC_JSON]))
    assert result["facts_accepted"] == 3
    assert result["facts_rejected"] == []
    assert uncited_facts(conn, brain) == []


def test_invented_attribute_without_quote_is_rejected(db):
    """A fact with no supporting quote in the capture is rejected, not guessed."""
    conn, brain = db
    cid = store.add_capture(conn, brain, "conversation", ATOMIC_CAPTURE, "test:3")
    bad_json = ('{"facts": [{"text": "Caroline is married",'
                ' "subject": "Caroline",'
                ' "quote": "Caroline married Sam in June",'
                ' "bucket": "people", "page_title": "Caroline",'
                ' "page_path": "people/caroline"}]}')
    result = compile_all(conn, brain, [cid], FakeClient([bad_json]))
    assert result["facts_accepted"] == 0
    assert len(result["facts_rejected"]) == 1
    assert uncited_facts(conn, brain) == []


# ---- Phase 7: subject resolution, claim dedupe, categorical contradictions,
# ---- weak-quote guard.

def test_subject_field_is_required():
    """Phase 7A: the extraction JSON must carry a subject; shape validation fails
    without it (one retry, then ExtractError)."""
    no_subject = ('{"facts": [{"text": "Caroline is single",'
                  ' "quote": "I am single", "bucket": "people",'
                  ' "page_title": "Caroline", "page_path": "people/caroline"}]}')
    with pytest.raises(ExtractError):
        extract(CAPTURE, FakeClient([no_subject, no_subject]))


def test_second_person_question_rejected_for_speaker(db):
    """Phase 7A defect D1b: Caroline asking Melanie about Melanie's marriage must
    not yield 'Caroline is married'."""
    capture = "Caroline: Wow, what an amazing family pic! How long have you been married?"
    conn, brain = db
    cid = store.add_capture(conn, brain, "conversation", capture, "test:p7a")
    fact = ('{"facts": [{"text": "Caroline is married", "subject": "Caroline",'
            ' "quote": "How long have you been married?", "bucket": "people",'
            ' "page_title": "Caroline", "page_path": "people/caroline"}]}')
    result = compile_all(conn, brain, [cid], FakeClient([fact]))
    assert result["facts_accepted"] == 0
    assert result["facts_rejected"][0][2].startswith("subject_mismatch")


def test_second_person_praise_rejected_for_speaker(db):
    """Phase 7A defect D1: Melanie praising Caroline's motherhood is rejected for
    Melanie, accepted for Caroline."""
    capture = ("Melanie: You're doing something amazing! You'll be an awesome mom!")
    conn, brain = db
    cid = store.add_capture(conn, brain, "conversation", capture, "test:p7b")
    bad = ('{"facts": [{"text": "Melanie is a great mom", "subject": "Melanie",'
           ' "quote": "You\'ll be an awesome mom!", "bucket": "people",'
           ' "page_title": "Melanie", "page_path": "people/melanie"}]}')
    good = ('{"facts": [{"text": "Caroline will be an awesome mom",'
            ' "subject": "Caroline",'
            ' "quote": "You\'ll be an awesome mom!", "bucket": "people",'
            ' "page_title": "Caroline", "page_path": "people/caroline"}]}')
    result = compile_all(conn, brain, [cid], FakeClient([bad]))
    assert result["facts_accepted"] == 0
    assert result["facts_rejected"][0][2].startswith("subject_mismatch")
    result2 = compile_all(conn, brain, [cid], FakeClient([good]))
    assert result2["facts_accepted"] == 1
    assert result2["facts_rejected"] == []


def test_first_person_fact_still_passes(db):
    """Phase 7A: first-person facts about the speaker are untouched."""
    conn, brain = db
    cid = _capture(db)
    result = compile_all(conn, brain, [cid], FakeClient([FACT_JSON]))
    assert result["facts_accepted"] == 1
    assert result["facts_rejected"] == []


def test_third_person_quote_requires_named_subject(db):
    """Phase 7A: when a quote names a recognisable person (a turn label), the fact's
    subject must be that person."""
    capture = "Caroline: Hey Melanie!\nMelanie: Caroline is so brave."
    conn, brain = db
    cid = store.add_capture(conn, brain, "conversation", capture, "test:p7c")
    good = ('{"facts": [{"text": "Caroline is so brave", "subject": "Caroline",'
            ' "quote": "Caroline is so brave", "bucket": "people",'
            ' "page_title": "Caroline", "page_path": "people/caroline"}]}')
    bad = ('{"facts": [{"text": "Melanie is so brave", "subject": "Melanie",'
           ' "quote": "Caroline is so brave", "bucket": "people",'
           ' "page_title": "Melanie", "page_path": "people/melanie"}]}')
    result = compile_all(conn, brain, [cid], FakeClient([bad]))
    assert result["facts_accepted"] == 0
    assert result["facts_rejected"][0][2].startswith("subject_mismatch")
    result2 = compile_all(conn, brain, [cid], FakeClient([good]))
    assert result2["facts_accepted"] == 1


def test_unresolvable_subject_rejected(db):
    """Phase 7A: no person signal and the subject is neither named nor the speaker."""
    conn, brain = db
    cid = store.add_capture(conn, brain, "conversation",
                            "Caroline: The wait can be hard.", "test:p7d")
    fact = ('{"facts": [{"text": "Melanie finds the wait hard", "subject": "Melanie",'
            ' "quote": "The wait can be hard.", "bucket": "people",'
            ' "page_title": "Melanie", "page_path": "people/melanie"}]}')
    result = compile_all(conn, brain, [cid], FakeClient([fact]))
    assert result["facts_accepted"] == 0
    assert result["facts_rejected"][0][2].startswith("subject_unresolved")


def test_near_duplicate_paraphrases_linked(db):
    """Phase 7B defect D2: paraphrases of the same claim collapse to one canonical
    fact; the others stay active with duplicate_of set, never retracted."""
    conn, brain = db
    cid = store.add_capture(conn, brain, "conversation",
                            "Caroline: I plan to become a single parent.", "test:p7e")
    variants = ('{"facts": ['
                ' {"text": "Caroline plans to become a single parent",'
                '  "subject": "Caroline", "quote": "I plan to become a single parent",'
                '  "bucket": "people", "page_title": "Caroline", "page_path": "people/caroline"},'
                ' {"text": "Caroline plans to become a single parent by adopting kids who need a family",'
                '  "subject": "Caroline", "quote": "I plan to become a single parent",'
                '  "bucket": "people", "page_title": "Caroline", "page_path": "people/caroline"},'
                ' {"text": "Caroline plans to become a single parent through adoption",'
                '  "subject": "Caroline", "quote": "I plan to become a single parent",'
                '  "bucket": "people", "page_title": "Caroline", "page_path": "people/caroline"}'
                ']}')
    result = compile_all(conn, brain, [cid], FakeClient([variants]))
    assert result["facts_accepted"] == 3
    assert result["duplicates_linked"] == 2
    page = store.get_page(conn, "people/caroline")["page"]
    all_facts = store.facts_for_page(conn, page["id"], include_duplicates=True)
    assert len(all_facts) == 3
    assert all(f["status"] == "active" for f in all_facts), "never retracted"
    dups = [f for f in all_facts if f["duplicate_of"] is not None]
    assert len(dups) == 2
    canonical = [f for f in all_facts if f["duplicate_of"] is None]
    assert len(canonical) == 1
    assert all(d["duplicate_of"] == canonical[0]["id"] for d in dups)


def test_single_vs_married_contradiction_superseded(db):
    """Phase 7C defect D4: the exact single-vs-married case must supersede."""
    conn, brain = db
    cid1 = store.add_capture(conn, brain, "conversation",
                             "Caroline: I am single.", "test:p7f1")
    cid2 = store.add_capture(conn, brain, "conversation",
                             "Caroline: I am married now.", "test:p7f2")
    f1 = ('{"facts": [{"text": "Caroline is single", "subject": "Caroline",'
          ' "quote": "I am single", "bucket": "people", "page_title": "Caroline",'
          ' "page_path": "people/caroline"}]}')
    f2 = ('{"facts": [{"text": "Caroline is married", "subject": "Caroline",'
          ' "quote": "I am married now", "bucket": "people", "page_title": "Caroline",'
          ' "page_path": "people/caroline"}]}')
    result = compile_all(conn, brain, [cid1, cid2], FakeClient([f1, f2]))
    assert result["superseded"] == 1
    page = store.get_page(conn, "people/caroline")["page"]
    facts = store.facts_for_page(conn, page["id"])
    active = [f for f in facts if f["status"] == "active"]
    assert len(active) == 1 and "married" in active[0]["text"]
    old = [f for f in facts if f["status"] == "superseded"][0]
    assert "single" in old["text"] and old["superseded_by"] == active[0]["id"]


def test_plan_fact_does_not_contradict_status_fact(db):
    """Phase 7C precision: 'plans to become a single parent' is a plan, not a
    status, so it must not supersede 'is married'."""
    conn, brain = db
    cid1 = store.add_capture(conn, brain, "conversation",
                             "Caroline: I am married.", "test:p7g1")
    cid2 = store.add_capture(conn, brain, "conversation",
                             "Caroline: I plan to become a single parent.", "test:p7g2")
    f1 = ('{"facts": [{"text": "Caroline is married", "subject": "Caroline",'
          ' "quote": "I am married", "bucket": "people", "page_title": "Caroline",'
          ' "page_path": "people/caroline"}]}')
    f2 = ('{"facts": [{"text": "Caroline plans to become a single parent",'
          ' "subject": "Caroline", "quote": "I plan to become a single parent",'
          ' "bucket": "people", "page_title": "Caroline", "page_path": "people/caroline"}]}')
    result = compile_all(conn, brain, [cid1, cid2], FakeClient([f1, f2]))
    assert result["superseded"] == 0


def test_weak_quote_rejected(db):
    """Phase 7D defect D3: a verbatim quote sharing no content token with the claim
    is rejected."""
    conn, brain = db
    cid = store.add_capture(conn, brain, "conversation",
                            "Caroline: I wish I had known you back then!", "test:p7h")
    fact = ('{"facts": [{"text": "Caroline was not married as of 2023-07-15",'
            ' "subject": "Caroline",'
            ' "quote": "I wish I had known you back then!", "bucket": "people",'
            ' "page_title": "Caroline", "page_path": "people/caroline"}]}')
    result = compile_all(conn, brain, [cid], FakeClient([fact]))
    assert result["facts_accepted"] == 0
    assert result["facts_rejected"][0][2].startswith("weak_quote")


def test_weak_quote_relaxed_when_quote_names_subject(db):
    """Phase 8B: the audit found 8 of 10 weak_quote rejections were valid facts, so a
    quote that names the subject now anchors the attribution. 'Mel supports Caroline'
    from "Thanks, Mel! Your backing really means a lot." (speaker Caroline) is a
    paraphrase with no content-token overlap, but the quote names the subject."""
    conn, brain = db
    cid = store.add_capture(conn, brain, "conversation",
                            "Caroline: Thanks, Mel! Your backing really means a lot.",
                            "test:p8b")
    fact = ('{"facts": [{"text": "Mel supports Caroline", "subject": "Mel",'
            ' "quote": "Thanks, Mel! Your backing really means a lot.",'
            ' "bucket": "people", "page_title": "Mel", "page_path": "people/mel"}]}')
    result = compile_all(conn, brain, [cid], FakeClient([fact]))
    assert result["facts_accepted"] == 1
    assert result["facts_rejected"] == []


def test_weak_quote_still_rejected_without_name_or_overlap(db):
    """Phase 8B: the relaxation only covers quotes that name the subject. A paraphrase
    that names nobody ("kids" vs "children") is still rejected."""
    conn, brain = db
    cid = store.add_capture(conn, brain, "conversation",
                            "Melanie: I'm swamped with the kids & work.", "test:p8b2")
    fact = ('{"facts": [{"text": "Melanie has children", "subject": "Melanie",'
            ' "quote": "I\'m swamped with the kids & work", "bucket": "people",'
            ' "page_title": "Melanie", "page_path": "people/melanie"}]}')
    result = compile_all(conn, brain, [cid], FakeClient([fact]))
    assert result["facts_accepted"] == 0
    assert result["facts_rejected"][0][2].startswith("weak_quote")


# ---- the maintainer: dogfooding on a real agent transcript (phase 12). The phase-7 subject rule
# ---- assumed people speaking in turns; agent logs use role labels and non-person subjects.

def test_entity_subject_accepted_when_quote_is_about_it(db):
    """'Phase 0 plan' is a project artifact, not a person: person grammar cannot judge it,
    so the only requirement is that the quote is actually about it."""
    conn, brain = db
    capture = "assistant: Phase 0 deliverables: scope, brief, and the eval harness."
    cid = store.add_capture(conn, brain, "chat", capture, "test:p12a")
    payload = ('{"facts": [{"text": "Phase 0 deliverables include the eval harness",'
               ' "subject": "Phase 0 deliverables",'
               ' "quote": "Phase 0 deliverables: scope, brief, and the eval harness.",'
               ' "bucket": "projects", "page_title": "Phase 0",'
               ' "page_path": "projects/phase-0"}]}')
    result = compile_all(conn, brain, [cid], FakeClient([payload]))
    assert result["facts_accepted"] == 1, result["facts_rejected"]


def test_entity_subject_rejected_when_quote_never_mentions_it(db):
    conn, brain = db
    capture = "assistant: The harness measures accuracy at 77.3%."
    cid = store.add_capture(conn, brain, "chat", capture, "test:p12b")
    payload = ('{"facts": [{"text": "Storage layer uses SQLite",'
               ' "subject": "the storage layer",'
               ' "quote": "The harness measures accuracy at 77.3%.",'
               ' "bucket": "projects", "page_title": "Storage",'
               ' "page_path": "projects/storage"}]}')
    result = compile_all(conn, brain, [cid], FakeClient([payload]))
    assert result["facts_accepted"] == 0
    reason = result["facts_rejected"][0][2]
    assert reason.startswith("subject_unresolved") or reason.startswith("weak_quote")


def test_role_speaker_does_not_reject_grounded_person_fact(db):
    """'assistant' is a role, not a person: 'I' cannot be resolved to it, so a fact about a
    named person must not be rejected merely because the speaker is a role label."""
    conn, brain = db
    capture = "assistant: Ged asked for a fully local build with no cloud inference."
    cid = store.add_capture(conn, brain, "chat", capture, "test:p12c")
    payload = ('{"facts": [{"text": "Ged required a fully local build",'
               ' "subject": "Ged",'
               ' "quote": "Ged asked for a fully local build with no cloud inference.",'
               ' "bucket": "people", "page_title": "Ged", "page_path": "people/ged"}]}')
    result = compile_all(conn, brain, [cid], FakeClient([payload]))
    assert result["facts_accepted"] == 1, result["facts_rejected"]


def test_locate_tolerates_markdown_and_unicode_formatting():
    """A quote that differs only cosmetically is still verbatim evidence; the returned span
    must be real capture text, never a normalised string."""
    capture = "**Capability clone.** Build phases 0–4 and stop — that is the recommendation."
    quote = "Capability clone. Build phases 0-4 and stop - that is the recommendation."
    span = locate(capture, quote)
    assert span is not None
    start, end = span
    assert capture[start:end].startswith("Capability clone.")
    assert "phases 0–4" in capture[start:end]
