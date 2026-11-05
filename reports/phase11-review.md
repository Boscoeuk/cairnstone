# Phase 11 — verified, plus a real defect CI exposed (the maintainer)

## CI now runs, and it caught something the local suite could not

Two runs failed before one passed:

1. `42123973932` — the workflow installed the package without pytest (`pip install -e .`).
2. `42124325866` — after installing pytest, **4 tests failed**: `test_brief_fails_loudly_when_endpoint_unreachable`,
   `test_build_brief_prefix_is_question_independent`, `test_build_brief_respects_budget_on_records`,
   `test_build_brief_admits_superseded_only_for_history`, all with
   `URLError: [Errno 111] Connection refused`.

That second failure was not a CI configuration problem. It was a real product defect: `retrieve.py`
called the embedding endpoint unconditionally, so **search and briefs raised an exception whenever
the embedding sidecar was down**. On this Mac the endpoint is always up, so 81 tests passed locally
and the defect was invisible. On a GitHub runner, or on any user's machine without the sidecar,
cairn simply did not work.

Fixed at the root rather than by skipping the tests:

- `cached_embeddings` now treats a connection failure as "no embeddings available": it returns the
  cached hits and does not cache the misses, so a later run with the endpoint up embeds properly
  instead of inheriting zero vectors.
- Search and brief scoring already had lexical and FTS components; they now treat a missing vector
  as zero similarity instead of skipping the row entirely, so lexical ranking still returns results.
- Two new tests assert that `build_brief` and `search` work against a deliberately dead embedding
  endpoint (`127.0.0.1:59999`).

Suite is now **83 passing**, and CI is green on the renamed repo:

```
42125582543  pytest (Python 3.12): success
             pytest (Python 3.10): success
             mcp extra import check: success
```

## Rename to Cairnstone — verified

- GitHub repo renamed: `Boscoeuk/cairn` → **`Boscoeuk/cairnstone`** (the old URL redirects).
- Local working directory `~/cairn` → `~/cairnstone`; remote URL updated.
- Distribution, Python package, CLI entry point, MCP server name and env-var prefix (`CAIRN_*` →
  `CAIRNSTONE_*`) all renamed in one pass, not partially. 83 tests pass after the rename.
- Fresh clone of the renamed repo, tested from scratch: **83 passed**.
- `v0.1.0` tagged and pushed; `gh api repos/Boscoeuk/cairnstone/tags` returns `v0.1.0`.
- `CHANGELOG.md` records the working-name change; `reports/` and `docs/phase*-brief.md` keep the
  old name deliberately, because they are dated evidence rather than current documentation.

## Not done

- **No PyPI release.** `cairnstone` is free on PyPI, but this machine has no PyPI credentials
  (no `~/.pypirc`, no `TWINE_*`/`PYPI_*` env vars). Publishing needs a token from Ged's PyPI account.
  Until then, install is `pip install git+https://github.com/Boscoeuk/cairnstone`.
- The MCP server remains verified against mcp 2.x only.
