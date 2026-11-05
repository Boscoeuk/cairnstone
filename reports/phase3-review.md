# Phase 3 — independent review and measured result (the maintainer)

## What was built

`src/cairn/retrieve.py` (hybrid search, embedding cache, prefix-stable `build_brief`,
citation rendering), a `cairn` backend in `eval/harness.py`, and a per-sample compiled DB
cache under `eval/results/cairn-db/`. Compiling sample 0 took 419 extraction calls and produced
419 facts across 16 pages.

## Measured (LoCoMo sample 0, 12 questions, local judge, TensorFold/GLM-5.3-Flash)

| backend | accuracy | mean context tokens | latency | cache hit |
|---|---|---|---|---|
| full_context | 83.3% | 15,043 | 3.15 s | 92% |
| cairn (whole-brain brief, verbose answer) | 75.0% | 4,341 | 1.66 s | 100% |
| cairn (whole-brain brief, terse answer) | 66.7% | 4,390 | 2.45 s | 83% |
| cairn (forced selection, 800-token budget) | 58.3% | 912 | 1.37 s | 92% |
| naive_rag | 66.7% | 770 | 2.38 s | 0% |

n=12. Directional only.

## Verdict: the thesis is NOT yet demonstrated

Cairn sits on the same accuracy/cost frontier as plain chunk-RAG rather than ahead of it.
At 4,390 tokens it matches naive_rag's 66.7% at 770 tokens — five times the cost for the same
accuracy. The 75% run used a prompt that restated facts, which the judge tolerates as
"extra detail", so part of that lead is judge leniency rather than knowledge.

**The compile layer works. The selection layer does not.**

## Diagnosis (from the compiled DB, not speculation)

The brain contains the correct facts. Three failures are interference, not ignorance:

- *"When did Melanie paint a sunrise?"* — the brain holds exactly one sunrise fact:
  "Melanie painted a lake sunrise in 2022". The answerer said **2023-07-15**, a date belonging
  to a different fact on the same page. With 121 facts in one brief, the answerer cannot tell
  which date belongs to which claim.
- *"When is Melanie planning on going camping?"* — the brain holds
  "Melanie is thinking about going camping in June 2023", plus **twelve** other camping facts
  (beach, forest, mountains, Perseid shower, annual trip…). The answerer replied "Not recorded."
  Too many near-identical distractors suppress the right one.
- *"When did Melanie run a charity race?"* — the fact "ran a charity race for mental health on
  2023-05-20" is present; the answerer returned a date from an unrelated fact.

This is the classic long-context interference problem: **more retrieved facts made answers
worse**. Chronology is what saved `full_context` — the raw transcript carries the ordering that
disambiguates which date belongs to which event, and a flat fact dump destroys it.

The 800-token run proves the corollary: forced selection collapsed to 58.3% because ranking is
currently page-level, not question-conditioned. Selecting *fewer* facts is right; selecting them
*badly* is worse than not selecting at all.

## Required next step

Question-conditioned fact selection, plus a metric that separates retrieval failure from
answering failure (`gold_support_in_brief`). Without that split we cannot tell whether to fix
ranking or fix the answerer. See `docs/phase4-brief.md`.
