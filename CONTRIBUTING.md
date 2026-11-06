# Contributing to Cairnstone

Thanks for looking at cairnstone. This document covers the two things you must know before
writing code: how to run the tests offline, and the project's hard constraints.

## Setup

```bash
git clone https://github.com/Boscoeuk/cairnstone
cd cairnstone
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python3 -m pytest -q
```

For MCP server work: `pip install ".[mcp]"`.

## Running tests offline

The full suite (87 tests) runs with **no model endpoint and no network**. Tests that
need the local model endpoint skip cleanly when it is unreachable — you do not need
any model endpoint to contribute. CI runs the same suite on Python 3.10
and 3.12 with no endpoint.

```bash
python3 -m pytest -q
```

## Hard constraints (do not break these)

- **Local-only inference.** Every model call goes to an endpoint on the local network
  (`CAIRN_BASE_URL`, `CAIRN_JUDGE_URL`, local embeddings). There is no cloud fallback and none
  may be added. If an endpoint is unreachable the tool fails loudly.
- **Citation rules.** Every fact must cite a capture id and character span; the verbatim
  quote is copied from that span at write time. A fact whose quote cannot be located in
  its capture is rejected, not guessed at. Never weaken this chain
  (`claim → capture → span → verbatim quote`).
- **Capture immutability.** Captures are never edited or deleted; corrections supersede.
- **Prefix-stable briefs.** Retrieval changes must not silently reorder earlier brief
  content.
- **No new runtime dependencies.** The runtime is stdlib + `requests`; the `mcp` extra is
  optional.

The compile policies are documented in `docs/compile-policies.md`.

## Pull requests

- One concern per PR; small, reviewable diffs.
- New behaviour gets a test; run `python3 -m pytest -q` and paste the result.
- Do not change measured numbers in the README or `eval/` without running the full eval
  and documenting the methodology.
- CI must be green before merge.
