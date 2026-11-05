# Phase 4 — verified result (the maintainer)

## The thesis now holds at n=12 — but n=12 is not evidence

| backend | accuracy | mean context tokens | latency |
|---|---|---|---|
| full_context | 83.3% | 15,043 | 3.15 s |
| naive_rag | 66.7% | 770 | 2.38 s |
| cairn, brief budget 600 | **91.7%** | 931 | 2.34 s |
| cairn, brief budget 1200 | **91.7%** | 1,613 | 3.42 s |
| cairn, brief budget 4000 | **100%** | 4,709 | 9.2 s (median) |

I spot-checked the b600 rows rather than trusting the aggregate: the answers are exact —
"2022", "Sweden", "2023-05-20", "June 2023", "4 years" — not judge leniency.

**Correction to the worker's report:** it states the 4000-budget run had a 35.4 s mean latency.
That is an artefact. Row 2 recorded 165.7 s with `tokens_per_second` 0.0 and a normal 9.3 s
prefill — a stalled request, not a real cost. Every other row is ~9 s. Mean latency is the
wrong statistic here; median plus an outlier flag is required.

## What actually fixed it

Selection, not the answer prompt. The diagnostic split confirms it: after question-conditioned
selection, answering failures went to zero and the single remaining failure is retrieval. The
phase-3 interference was distractor density, and the twelve camping facts now collapse to one.

The one failure ("When did Caroline get married?" → gold "Single") is a **compile-layer** gap:
the brain holds "Caroline plans to become a single parent…" but no atomic "Caroline is single"
fact. No selector can retrieve direct support that was never extracted. That is the extractor's
job, not the ranker's.

## The cache trade-off is real and accepted

Cache hit is 0 at every phase-4 budget. The stable prefix is now a ~130-token entity directory
and the selected evidence sits in the volatile message, so there is little left to reuse.
The phase-3 200x TTFT win was bought with a 4,000-token cached prefix that also carried the
interference. Phase 4 trades cache value for accuracy per token, and latency stays at 2.3 s
because the whole prompt is small. This is the right trade at this corpus size.

## What is still unproven

n=12, one conversation, local-judged. One question flip is 8.3 points. Nothing here is
statistically settled until the measurement covers many more questions across several
conversations. That is phase 5.
