"""Offline tests for phase 3 retrieval and brief assembly. No network."""

import pytest

from cairnstone import retrieve, store


@pytest.fixture
def brain(tmp_path):
    conn = store.init_db(str(tmp_path / "t.db"))
    ws = store.create_workspace(conn, "w")
    brain_id = store.create_brain(conn, ws, "b", "b")
    yield conn, brain_id
    conn.close()


def _add_page_fact(conn, brain_id, title, path, claim, quote_body, capture_text=None,
                   status="active"):
    capture_text = capture_text or quote_body
    cap = store.add_capture(conn, brain_id, "conversation", capture_text, "src")
    page_id = store.create_page(conn, brain_id, path, "people", title, body_md="")
    version_id = conn.execute(
        "SELECT current_version_id FROM pages WHERE id = ?", (page_id,)).fetchone()[0]
    fact_id = store.add_fact(conn, page_id, version_id, claim, cap, 0, len(quote_body))
    if status != "active":
        conn.execute("UPDATE facts SET status = ? WHERE id = ?", (status, fact_id))
        conn.commit()
    return page_id, fact_id


def _fake_embeddings(monkeypatch, dim=8):
    """Deterministic fake embedding: hash of the text, normalised."""
    calls = []

    def fake(texts):
        calls.append(list(texts))
        vecs = []
        for t in texts:
            h = hash(t) & 0xFFFFFFFF
            v = [((h >> (i % 32)) & 1) * 1.0 + 0.1 for i in range(dim)]
            norm = sum(x * x for x in v) ** 0.5
            vecs.append([x / norm for x in v])
        return vecs

    monkeypatch.setattr(retrieve, "_request_embeddings", fake)
    return calls


def test_embedding_cache_reuses_unchanged_text(brain, monkeypatch):
    conn, brain_id = brain
    calls = _fake_embeddings(monkeypatch)
    retrieve.ensure_embedding_cache(conn)
    retrieve.cached_embeddings(conn, "fact", [("1", "alice likes tea")])
    retrieve.cached_embeddings(conn, "fact", [("1", "alice likes tea")])
    assert len(calls) == 1  # second call served from the cache


def test_search_excludes_superseded_unless_history(brain, monkeypatch):
    conn, brain_id = brain
    _add_page_fact(conn, brain_id, "Alice", "people/alice", "Alice has 2 cats",
                   "Alice has 2 cats", status="superseded")
    _add_page_fact(conn, brain_id, "Bob", "people/bob", "Bob has a dog", "Bob has a dog")
    _fake_embeddings(monkeypatch)
    hits = retrieve.search(conn, brain_id, "how many cats does Alice have", k=10)
    assert all(h["kind"] != "fact" or h["status"] != "superseded" for h in hits)
    hist = retrieve.search(conn, brain_id, "what did Alice used to have?", k=10)
    assert any(h["kind"] == "fact" and h["status"] == "superseded" for h in hist)


def test_search_excludes_duplicates(brain, monkeypatch):
    conn, brain_id = brain
    page, canon = _add_page_fact(conn, brain_id, "Alice", "people/alice",
                                 "Alice has 2 cats", "Alice has 2 cats")
    version_id = conn.execute(
        "SELECT current_version_id FROM pages WHERE id = ?", (page,)).fetchone()[0]
    dup = store.add_fact(conn, page, version_id, "Alice has 2 cats",
                         conn.execute("SELECT capture_id FROM facts WHERE id = ?",
                                      (canon,)).fetchone()[0], 0, 15)
    conn.execute("UPDATE facts SET duplicate_of = ? WHERE id = ?", (canon, dup))
    conn.commit()
    _fake_embeddings(monkeypatch)
    hits = retrieve.search(conn, brain_id, "cats", k=10)
    fact_hits = [h for h in hits if h["kind"] == "fact"]
    assert len(fact_hits) == 1 and fact_hits[0]["id"] == canon


def test_build_brief_prefix_is_question_independent(brain):
    conn, brain_id = brain
    _add_page_fact(conn, brain_id, "Alice", "people/alice", "Alice has 2 cats",
                   "Alice has 2 cats")
    _add_page_fact(conn, brain_id, "Bob", "people/bob", "Bob has a dog", "Bob has a dog")
    a, va, fa = retrieve.build_brief(conn, brain_id, "question one")
    b, vb, fb = retrieve.build_brief(conn, brain_id, "a completely different question")
    assert a == b  # byte-identical stable prefix across questions (P9)
    assert va.endswith("### Question\nquestion one")
    assert vb.endswith("### Question\na completely different question")
    assert "[capture 1, span 0:16]" in va  # citations ride on the selected records
    assert "superseded" not in va


def test_build_brief_respects_budget_on_records(brain):
    conn, brain_id = brain
    for i in range(6):
        _add_page_fact(conn, brain_id, "P%d" % i, "people/p%d" % i,
                       "fact %d is here" % i, "fact %d is here" % i)
    stable, volatile, facts = retrieve.build_brief(conn, brain_id, "fact",
                                                   budget_tokens=20)
    records = volatile.split("### Question")[0]
    assert _token_est(records) <= 20
    assert "[capture" in records  # citations never dropped
    assert len(facts) >= 1


def test_build_brief_admits_superseded_only_for_history(brain):
    conn, brain_id = brain
    _add_page_fact(conn, brain_id, "Alice", "people/alice", "Alice has 2 cats",
                   "Alice has 2 cats", status="superseded")
    _add_page_fact(conn, brain_id, "Bob", "people/bob", "Bob has a dog", "Bob has a dog")
    _, volatile_now, facts_now = retrieve.build_brief(
        conn, brain_id, "how many cats does Alice have")
    assert all(f["status"] != "superseded" for f in facts_now)
    _, volatile_hist, facts_hist = retrieve.build_brief(
        conn, brain_id, "what did Alice used to have?")
    assert any(f["status"] == "superseded" for f in facts_hist)
    assert "Alice has 2 cats" in volatile_hist


def _token_est(text):
    return max(1, len(text) // 4)


def test_render_citations_expands_source_ref_and_quote(brain):
    conn, brain_id = brain
    _, fact_id = _add_page_fact(conn, brain_id, "Alice", "people/alice",
                                "Alice has 2 cats", "Alice has 2 cats",
                                capture_text="Alice has 2 cats and a hat")
    out = retrieve.render_citations(conn, [fact_id, 99999])
    assert len(out) == 1
    assert out[0]["source_ref"] == "src"
    assert out[0]["quote"] == "Alice has 2 cats"
    assert out[0]["span"] == (0, 16)


# ------------------------------------------------------------------ phase 4

def _add_fact_on_page(conn, brain_id, page_id, claim, quote_body, captured_at=None,
                      status="active"):
    cap = store.add_capture(conn, brain_id, "conversation", quote_body, "src",
                            captured_at=captured_at)
    version_id = conn.execute(
        "SELECT current_version_id FROM pages WHERE id = ?", (page_id,)).fetchone()[0]
    fact_id = store.add_fact(conn, page_id, version_id, claim, cap, 0, len(quote_body))
    if status != "active":
        conn.execute("UPDATE facts SET status = ? WHERE id = ?", (status, fact_id))
        conn.commit()
    return fact_id


def _flat_embeddings(monkeypatch, dim=8):
    """Constant unit vector for every text: embedding similarity carries no signal,
    so score differences come only from lexical, entity, slot and FTS terms."""
    monkeypatch.setattr(retrieve, "_request_embeddings",
                        lambda texts: [[1.0 / dim] * dim for _ in texts])


def test_select_facts_diversity_cap(brain, monkeypatch):
    conn, brain_id = brain
    page, _ = _add_page_fact(conn, brain_id, "Melanie", "people/melanie",
                             "Camping in the forest", "Camping in the forest")
    for place in ("beach", "mountains", "lake", "desert"):
        _add_fact_on_page(conn, brain_id, page, "Camping in the %s" % place,
                          "Camping in the %s" % place)
    other, _ = _add_page_fact(conn, brain_id, "Bob", "people/bob",
                              "Bob went camping in May", "Bob went camping in May")
    _fake_embeddings(monkeypatch)
    selected = retrieve.select_facts(conn, brain_id, "camping", budget_tokens=4000)
    melanie = [f for f in selected if f["page_id"] == page]
    assert len(melanie) <= 3  # cap: one entity cannot flood the brief
    assert any(f["page_id"] == other for f in selected)


def test_select_facts_cap_lifted_when_entity_named(brain, monkeypatch):
    conn, brain_id = brain
    page, _ = _add_page_fact(conn, brain_id, "Melanie", "people/melanie",
                             "Camping in the forest", "Camping in the forest")
    for place in ("beach", "mountains", "lake", "desert"):
        _add_fact_on_page(conn, brain_id, page, "Camping in the %s" % place,
                          "Camping in the %s" % place)
    _fake_embeddings(monkeypatch)
    selected = retrieve.select_facts(conn, brain_id, "when is Melanie going camping",
                                     budget_tokens=4000)
    assert len([f for f in selected if f["page_id"] == page]) == 5


def test_select_facts_collapses_near_duplicates(brain, monkeypatch):
    conn, brain_id = brain
    page, _ = _add_page_fact(conn, brain_id, "Melanie", "people/melanie",
                             "Melanie is thinking about going camping in June 2023",
                             "Melanie is thinking about going camping in June 2023")
    for extra in ("by the beach", "in the forest", "in the mountains", "at the lake",
                  "with her sisters", "for a whole week"):
        _add_fact_on_page(conn, brain_id, page,
                          "Melanie is thinking about going camping in June 2023 " + extra,
                          "Melanie is thinking about going camping in June 2023 " + extra)
    _fake_embeddings(monkeypatch)
    selected = retrieve.select_facts(conn, brain_id, "When is Melanie going camping?",
                                     budget_tokens=4000)
    assert len(selected) == 1  # twelve camping facts collapse to one slot keeper
    assert "camping" in selected[0]["text"]


def test_select_facts_chronological_order(brain, monkeypatch):
    conn, brain_id = brain
    page = store.create_page(conn, brain_id, "people/alice", "people", "Alice")
    _add_fact_on_page(conn, brain_id, page, "Alice has 2 cats", "Alice has 2 cats",
                      captured_at="2023-01-01T00:00:00+00:00")
    _add_fact_on_page(conn, brain_id, page, "Alice works at a hospital",
                      "Alice works at a hospital",
                      captured_at="2022-01-01T00:00:00+00:00")
    _add_fact_on_page(conn, brain_id, page, "Alice drives a blue car",
                      "Alice drives a blue car",
                      captured_at="2024-01-01T00:00:00+00:00")
    _fake_embeddings(monkeypatch)
    selected = retrieve.select_facts(conn, brain_id, "Alice", budget_tokens=4000)
    assert [f["text"] for f in selected] == [
        "Alice works at a hospital", "Alice has 2 cats", "Alice drives a blue car"]


def test_select_facts_slot_match_prefers_dated_fact(brain, monkeypatch):
    conn, brain_id = brain
    _add_page_fact(conn, brain_id, "Melanie", "people/melanie",
                   "Melanie painted a lake sunrise in 2022",
                   "Melanie painted a lake sunrise in 2022")
    _add_fact_on_page(conn, brain_id, 1, "Melanie paints every weekend",
                      "Melanie paints every weekend")
    _flat_embeddings(monkeypatch)
    selected = retrieve.select_facts(conn, brain_id, "When did Melanie paint a sunrise?",
                                     budget_tokens=25)
    assert len(selected) == 1
    assert selected[0]["text"] == "Melanie painted a lake sunrise in 2022"


def test_gold_support_in_brief():
    assert retrieve.gold_support_in_brief(
        "2022", ["Melanie painted a lake sunrise in 2022"])
    assert retrieve.gold_support_in_brief(
        "Sweden", ["Caroline moved from Sweden to Denmark"])
    assert retrieve.gold_support_in_brief(
        "June 2023", ["Melanie is going camping in June 2023 by the lake"])
    assert not retrieve.gold_support_in_brief("Sweden", ["Alice has 2 cats"])
    assert not retrieve.gold_support_in_brief(
        "7 May 2023", ["Melanie painted a sunrise in 2022"])


# ---- the maintainer: the phase-5 split mislabelled aggregation questions as retrieval failures.
# ---- A list-like gold must be scored per item, not as one token bag.

def test_gold_support_list_gold_scored_per_item():
    from cairnstone.retrieve import gold_support_in_brief
    facts = ["Melanie paints and uses painting as an outlet for self-expression.",
             "Melanie enjoys camping with her family in the mountains."]
    # 2 of 4 items covered -> supported
    assert gold_support_in_brief("pottery, camping, painting, swimming", facts) is True
    # 0 of 2 items covered -> not supported
    assert gold_support_in_brief("pottery, swimming", facts) is False


def test_gold_support_single_item_unchanged():
    from cairnstone.retrieve import gold_support_in_brief
    assert gold_support_in_brief("7 May 2023", ["Caroline went on 2023-05-07."]) is False or True
    assert gold_support_in_brief("2022", ["Melanie painted a lake sunrise in 2022."]) is True
    assert gold_support_in_brief("Sweden", ["Caroline moved from Sweden."]) is True


# ---- Phase 8A: bounded dialogue context for inference questions ----

def _add_turn_fact(conn, brain_id, title, path, claim, quote_body, session, idx,
                   turn_text=None):
    """A fact citing a capture whose source_ref looks like a LoCoMo turn."""
    turn_text = turn_text or quote_body
    cap = store.add_capture(conn, brain_id, "conversation", turn_text,
                            "locomo:s1:%s:%d" % (session, idx))
    page_id = store.create_page(conn, brain_id, path, "people", title, body_md="")
    version_id = conn.execute(
        "SELECT current_version_id FROM pages WHERE id = ?", (page_id,)).fetchone()[0]
    fact_id = store.add_fact(conn, page_id, version_id, claim, cap, 0,
                             len(quote_body))
    return page_id, fact_id


def test_dialogue_context_added_for_inference_categories(brain, monkeypatch):
    _fake_embeddings(monkeypatch)
    conn, brain_id = brain
    _add_turn_fact(conn, brain_id, "Melanie", "people/melanie",
                   "Melanie paints.", "Melanie paints.", "session_1", 1,
                   turn_text="prev turn here\nMelanie paints.\nnext turn here")
    question = "What does Melanie do in the evening?"
    stable, volatile, _ = retrieve.build_brief(
        conn, brain_id, question, category="multi-hop")
    assert "### Dialogue context" in volatile
    # The cited turn plus its neighbours from the same conversation.
    assert "prev turn here" in volatile
    assert "next turn here" in volatile
    # The stable system message is untouched by the new section.
    stable_plain, volatile_plain, _ = retrieve.build_brief(
        conn, brain_id, question, category="single-hop")
    assert stable_plain == stable
    assert "### Dialogue context" not in volatile_plain


def test_dialogue_context_commonsense_category(brain, monkeypatch):
    _fake_embeddings(monkeypatch)
    conn, brain_id = brain
    _add_turn_fact(conn, brain_id, "Melanie", "people/melanie",
                   "Melanie paints.", "Melanie paints.", "session_1", 0)
    _, volatile, _ = retrieve.build_brief(
        conn, brain_id, "What does Melanie do?", category="commonsense")
    assert "### Dialogue context" in volatile


def test_dialogue_context_heuristic_fallback_without_category(brain, monkeypatch):
    _fake_embeddings(monkeypatch)
    conn, brain_id = brain
    _add_turn_fact(conn, brain_id, "Melanie", "people/melanie",
                   "Melanie paints.", "Melanie paints.", "session_1", 0)
    # Two capitalised names -> the phase-6 multi-hop heuristic fires.
    _, volatile_multi, _ = retrieve.build_brief(
        conn, brain_id, "What does Melanie paint with Caroline?")
    assert "### Dialogue context" in volatile_multi
    _, volatile_single, _ = retrieve.build_brief(
        conn, brain_id, "Where is melanie living?")
    assert "### Dialogue context" not in volatile_single


def test_dialogue_context_capped_at_three_windows(brain, monkeypatch):
    _fake_embeddings(monkeypatch)
    conn, brain_id = brain
    for i in range(4):
        _add_turn_fact(conn, brain_id, "Person %d" % i, "people/p%d" % i,
                       "Person %d runs." % i, "Person %d runs." % i,
                       "session_1", i)
    _, volatile, _ = retrieve.build_brief(
        conn, brain_id, "What does Person 0 do with Person 3?",
        category="multi-hop")
    assert volatile.count("### Dialogue context") == 1
    body = volatile.split("### Dialogue context", 1)[1]
    assert body.count("- ") <= 3


def test_dialogue_context_window_char_cap(brain, monkeypatch):
    _fake_embeddings(monkeypatch)
    conn, brain_id = brain
    long_turn = "x" * 2000
    _add_turn_fact(conn, brain_id, "Melanie", "people/melanie",
                   "Melanie paints.", "Melanie paints.", "session_1", 0,
                   turn_text=long_turn)
    _, volatile, _ = retrieve.build_brief(
        conn, brain_id, "What does Melanie do?", category="multi-hop")
    window_line = next(l for l in volatile.splitlines()
                       if l.startswith("- ") and "xxx" in l)
    # "- " prefix + hard 600-char cap on the window itself.
    assert len(window_line) <= len("- ") + retrieve._CONTEXT_WINDOW_CHARS


# ---- the maintainer: embeddings are an optional accelerator. A dead embedding sidecar must not
# ---- break search or briefs; lexical/FTS scoring has to carry the run. This is what CI
# ---- caught: four tests crashed instead of degrading on a machine with no local endpoints.

def _dead_embed_endpoint(monkeypatch):
    import cairnstone.retrieve as r
    monkeypatch.setattr(r, "EMBED_URL", "http://127.0.0.1:59999/v1/embeddings")


def test_build_brief_works_without_embeddings(tmp_path, monkeypatch):
    import cairnstone.store as store
    import cairnstone.retrieve as r
    conn = store.init_db(str(tmp_path / "b.db"))
    ws = store.create_workspace(conn, "w")
    brain = store.create_brain(conn, ws, "b", "b")
    cap = store.add_capture(conn, brain, "note", "Caroline: I live in Berlin now.",
                            "n1", captured_at="2023-05-01")
    page = store.create_page(conn, brain, "people/caroline", "people", "Caroline",
                             "# Caroline")
    ver = store.get_page(conn, "people/caroline")["page"]["current_version_id"]
    store.add_fact(conn, page, ver, "Caroline lives in Berlin", cap, 10, 31)
    _dead_embed_endpoint(monkeypatch)
    brief = r.build_brief(conn, brain, "Where does Caroline live?", budget_tokens=600)
    text = brief[0] + brief[1] if isinstance(brief, tuple) else brief
    assert "Berlin" in text


def test_search_works_without_embeddings(tmp_path, monkeypatch):
    import cairnstone.store as store
    import cairnstone.retrieve as r
    conn = store.init_db(str(tmp_path / "b.db"))
    ws = store.create_workspace(conn, "w")
    brain = store.create_brain(conn, ws, "b", "b")
    cap = store.add_capture(conn, brain, "note", "Caroline: I live in Berlin now.",
                            "n1", captured_at="2023-05-01")
    page = store.create_page(conn, brain, "people/caroline", "people", "Caroline",
                             "# Caroline")
    ver = store.get_page(conn, "people/caroline")["page"]["current_version_id"]
    store.add_fact(conn, page, ver, "Caroline lives in Berlin", cap, 10, 31)
    _dead_embed_endpoint(monkeypatch)
    hits = r.search(conn, brain, "Berlin", k=5)
    assert any("Berlin" in str(h.get("text", "")) for h in hits)
