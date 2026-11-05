# Cairn (working name)

A **local-first memory compiler for AI agents**. It reads what a team or a single operator
produces — conversations, notes, documents, agent session logs — and compiles it into
Markdown pages about people, projects, decisions and customers, where **every fact carries a
citation to the exact source it came from**. A nightly pass merges duplicates, supersedes stale
facts, and flags contradictions without destroying history.

This is an independent open-source reimplementation of the *capability* of commercial
"living memory" products (livingbrain.com by ChatAndBuild). It is not a clone of their code,
their UI, or their pricing model — it is a clone of the **compile-and-retrieve capability**,
built to run entirely on local hardware.

## Hard constraints

- **No cloud inference.** Every model call goes to an endpoint on the local network:
  - compiler/primary: `glm-5.3-flash` → `http://127.0.0.1:8460/v1` (`glm-5.3-flash`)
  - second worker / judge: `local-judge` → `http://127.0.0.1:8889/v1` (`local-judge`)
  - embeddings: `http://127.0.0.1:1234/v1` (`text-embedding-nomic-embed-text-v1.5`, 768d)
- If an endpoint is unreachable the service fails loudly. There is no cloud fallback.
- Data stays on disk. SQLite + Markdown export. Nothing leaves the machine.
- Apache-2.0.

## Status

Phase 0 — evaluation harness. Nothing is a product yet. Do not describe features as working
until the eval harness or a test proves them.

## Why a harness first

The commercial product's headline claims (92.2% on LoCoMo at ~9.4K context tokens, 22.6x token
reduction on LongMemEval-S) are self-reported. LoCoMo and LongMemEval are public, so the claims
are reproducible. We build the measurement before the product, so every compile-policy decision
is scored rather than guessed. Our numbers are **local-judged** (GLM as judge, not GPT-4o) and
must always be labelled as such — they are comparable in shape, not identical in judge.
