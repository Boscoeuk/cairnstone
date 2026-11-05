DONE: Phase 2 compile pipeline implemented — extraction with verbatim-quote citation, page placement, dedupe, contradiction supersede; 26 tests pass; live smoke run against TensorFold at 127.0.0.1:8460 with 0 uncited facts.

FILES:
- src/cairn/llm.py (new) — OpenAI-compatible client for the local endpoint. Sends `chat_template_kwargs: {"enable_thinking": think}` (top-level flag is ignored by TensorFold). Stable instruction block is its own leading system message, volatile capture in a later user message, per docs/tensorfold-integration.md so the per-message-boundary prefix cache can hit. Records engine telemetry (tokens_per_second, prefill_seconds, time_to_first_token, cached_tokens) per call and exposes it via `client.telemetry_last()`. No cloud, `Authorization: Bearer local` only.
- src/cairn/compile.py (new) — the pipeline: `extract` (JSON facts, validate shape, one stricter retry on invalid JSON, then ExtractError → capture recorded as failed), `locate` (exact substring search; whitespace-normalised fallback mapped back to real offsets; returns None otherwise — no guesswork), `upsert_page` (reuses existing path), `write_facts` (via `store.add_fact`, so the store's own citation checks also apply), `dedupe` (identical active fact text on the same page → older marked `retracted`, never deleted), `supersede_contradictions` (same subject/slot, different value → older capture superseded via `store.supersede_fact`, `superseded_by` set, history kept), `compile_all`, `uncited_facts` (verification helper), and `python3 -m cairn.compile --smoke`.
- tests/test_compile.py (new) — offline tests, FakeClient monkeypatch, no network.

RAN:
- `PYTHONPATH=src python3 -m pytest -q`
- `PYTHONPATH=src python3 -m cairn.compile --smoke` (twice, against the live endpoint)

OUTPUT (pytest):
```
..........................                                               [100%]
26 passed in 0.16s
```

OUTPUT (smoke, live):
```
captures in: 10
failed captures: none
facts accepted: 7
facts rejected: 0
duplicates removed: 0
superseded: 0
pages created: 2
uncited facts: 0 (must be 0)
engine telemetry (last call): {"engine": "glm-zig", "tokens_per_second": 66.57, "prefill_seconds": 0.748, "time_to_first_token": 0.899, "cached_tokens": 0, "prompt_tokens": 221, "completion_tokens": 66, "elapsed_seconds": 1.877}
```

NOTES / DECISIONS:
- `dedupe` marks duplicates `retracted` rather than a new status: the facts table CHECK constraint (`status IN ('active','superseded','retracted')`) forbids inventing a `'duplicate'` status, and store.py is the maintainer's. No store.py changes were needed or made.
- Contradiction detection keys on fact text with the last number/date/weekday token treated as the value; two active facts on the same page with the same key but different values supersede the older-capture one. Deterministic, no model call.
- `locate`'s normalised fallback maps matches back through a position table so spans always point at real capture text; `store.add_fact` re-validates spans independently.
- Smoke acceptance from the brief: 0 uncited facts — confirmed. Zero rejections on this run because the model's quotes landed verbatim; the rejection path is covered by tests (absent quote → rejected with reason).

UNVERIFIED:
- Prefix-cache hit on the smoke run: `cached_tokens: 0` because each capture is a different volatile user message against a short (~221 token) system prefix; the cache benefit shows at scale with a larger stable prefix. The message-boundary structure required for hits is in place and matches the measured behaviour in docs/tensorfold-integration.md.
- Nightly evolution pass scheduling (cron/loop) is out of the phase-2 brief scope; `dedupe` + `supersede_contradictions` are the callable units.
