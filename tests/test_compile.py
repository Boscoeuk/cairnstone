"""Offline tests for the phase 2 compile pipeline (no network)."""

import pytest

from cairn import store
from cairn.compile import (ExtractError, compile_all, dedupe, extract, locate,
                           supersede_contradictions, upsert_page, write_facts)
from cairn.llm import LLMError


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
                             "Again: I am a transgender woman.", "test:2")
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
          ' "quote": "I started hormones in March", "bucket": "decisions",'
          ' "page_title": "Hormones", "page_path": "decisions/hormones"}]}')
    f2 = ('{"facts": [{"text": "Caroline started hormones in April",'
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
    facts = [{"text": "x", "quote": "I am a transgender woman",
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
    from cairn.compile import EXTRACTION_SYSTEM
    assert "absolute date" in EXTRACTION_SYSTEM
    assert "YYYY-MM-DD" in EXTRACTION_SYSTEM


def test_code_fenced_json_is_parsed():
    client = FakeClient(["```json\n" + FACT_JSON + "\n```"])
    facts = extract(CAPTURE, client)
    assert len(facts) == 1 and facts[0]["page_path"] == "people/caroline"


def test_dedupe_links_not_retracts(db):
    conn, brain = db
    cid = _capture(db)
    cid2 = store.add_capture(conn, brain, "conversation",
                             "Again: I am a transgender woman.", "test:2")
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
    f1 = ('{"facts": [{"text": "Alice has 2 cats", "quote": "I have 2 cats",'
          ' "bucket": "people", "page_title": "Alice", "page_path": "people/alice"}]}')
    f2 = ('{"facts": [{"text": "Alice has 3 dogs", "quote": "I have 3 dogs",'
          ' "bucket": "people", "page_title": "Alice", "page_path": "people/alice"}]}')
    result = compile_all(conn, brain, [cid1, cid2], FakeClient([f1, f2]))
    assert result["facts_accepted"] == 2
    assert result["superseded"] == 0, "different slots must not supersede"


def test_month_day_contradiction_detected(db):
    from cairn.compile import _split_subject_slot
    k1, v1 = _split_subject_slot("Billing v2 ships Mar 31")
    k2, v2 = _split_subject_slot("Billing v2 ships Apr 30")
    assert k1 == k2, "same slot despite different dates"
    assert v1 != v2


def test_export_excludes_duplicates(db, tmp_path):
    conn, brain = db
    cid = _capture(db)
    cid2 = store.add_capture(conn, brain, "conversation",
                             "Again: I am a transgender woman.", "test:2")
    compile_all(conn, brain, [cid, cid2], FakeClient([FACT_JSON, FACT_JSON]))
    out = tmp_path / "export"
    store.export_markdown(conn, brain, str(out))
    text = (out / "people" / "caroline.md").read_text()
    assert text.count("- Caroline is a transgender woman") == 1
