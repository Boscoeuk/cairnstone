# Phase 6 baseline — corrected measurement (the maintainer)

Scope is now genuinely 2 conversations (conv-26, conv-30) × 30 questions = 60, with brains
recompiled so the atomic-fact rule is live (confirmed: "Caroline is single" now exists).

| backend | accuracy | mean context tokens | median latency | cache hit |
|---|---|---|---|---|
| cairn, 600-token brief | **71.7%** | 1,141 | 2.13 s | 48% |
| full_context | 50.0% | 13,277 | 0.32 s | 97% |
| naive_rag | 36.7% | 907 | 2.44 s | 0% |

Cairn is +21.7 points over full context at 11.6x fewer tokens, and +35 points over naive_rag at
comparable tokens. This is the first measurement with real multi-conversation coverage, and it
holds.

## The win is narrower than the headline

By category:

| category | cairn | full_context | naive_rag |
|---|---|---|---|
| temporal (n=34) | **85.3%** | 29.4% | 17.6% |
| multi-hop (n=20) | 50.0% | **75.0%** | 50.0% |
| commonsense (n=4) | 50.0% | 75.0% | **100%** |
| single-hop (n=2) | 100% | 100% | 100% |

Cairn's entire advantage is temporal: date-resolved, cited facts beat a 13k-token transcript
badly there. On multi-hop and commonsense, the raw transcript wins — cross-turn inference needs
the surrounding conversation, and a flat fact set loses it. That is a real limitation of the
compiled representation, not a tuning artefact.

## Where the remaining failures are

Corrected diagnostic on cairn: 53/60 briefs contained gold support, **2 retrieval failures,
15 answering failures**. The bottleneck has moved. Selection is no longer the problem; the
answerer cannot convert present evidence into the right answer, and the failures concentrate in
multi-hop (aggregation across several facts) and commonsense (inference).

## One compile defect to check

The recompiled brain contains "Melanie plans to become a single parent". Melanie has kids and a
partner, so this is a likely mis-attribution or an over-eager inference from the atomic-attribute
rule added in phase 5. It must be verified against its quote before being trusted.
