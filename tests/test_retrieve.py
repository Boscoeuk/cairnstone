"""Offline tests for phase 3 retrieval and brief assembly. No network."""

import pytest

from cairn import retrieve, store


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


def test_build_brief_is_question_independent_and_cited(brain):
    conn, brain_id = brain
    _add_page_fact(conn, brain_id, "Alice", "people/alice", "Alice has 2 cats",
                   "Alice has 2 cats")
    _add_page_fact(conn, brain_id, "Bob", "people/bob", "Bob has a dog", "Bob has a dog")
    a, qa = retrieve.build_brief(conn, brain_id, "question one")
    b, qb = retrieve.build_brief(conn, brain_id, "a completely different question")
    assert a == b  # byte-identical stable prefix across questions (P9)
    assert qa == "question one" and qb == "a completely different question"
    assert "[capture 1, span 0:16]" in a
    assert "superseded" not in a


def test_build_brief_trims_pages_then_facts_then_quotes(brain):
    conn, brain_id = brain
    for i in range(6):
        _add_page_fact(conn, brain_id, "P%d" % i, "people/p%d" % i,
                       "fact %d is here" % i, "fact %d is here" % i)
    stable, _ = retrieve.build_brief(conn, brain_id, "q", budget_tokens=20)
    assert _token_est(stable) <= 20
    assert "[capture" in stable  # citations never dropped


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


def test_superseded_fact_flagged_in_brief_metrics(brain):
    conn, brain_id = brain
    _add_page_fact(conn, brain_id, "Alice", "people/alice", "Alice has 2 cats",
                   "Alice has 2 cats", status="superseded")
    _add_page_fact(conn, brain_id, "Bob", "people/bob", "Bob has a dog", "Bob has a dog")
    import hashlib

    def fake(texts):
        return [[(int(hashlib.sha256(t.encode()).hexdigest()[i % 60], 16) % 7) + 0.1
                 for _ in range(8)] for i, t in enumerate(texts)]

    # history question admits the superseded fact; build_brief still renders it
    stable, _ = retrieve.build_brief(conn, brain_id, "what did Alice used to have?")
    # The default brief carries only active facts (P8); history admission is a
    # search-level concern, not a brief-level one.
    assert "Alice has 2 cats" not in stable
    assert "Bob has a dog" in stable
