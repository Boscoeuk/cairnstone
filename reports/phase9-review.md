# Phase 9 — verified (the maintainer)

Reproduces: cairn **77.3%** at 1,276 tokens, median 2.83 s, n=150. full_context 53.3% at 13,278;
naive_rag 45.3% at 932. 69 tests pass.

| category | phase 8 | phase 9 | full_context | naive_rag |
|---|---|---|---|---|
| temporal (n=61) | 90.2% | 88.5% | 32.8% | 26.2% |
| multi-hop (n=40) | 67.5% | 67.5% | 57.3% | 33.3% |
| single-hop (n=38) | 68.4% | **73.7%** | 76.3% | 76.3% |
| commonsense (n=11) | 54.5% | **63.6%** | 72.7% | 90.9% |

Single-hop recovered 5.3 points and commonsense 9.1 points; the gap to the baselines on single-hop
is now 2.6 points instead of 8. "Not recorded" answers fell to 9/150. Answers remain terse (mean
39.7 characters, max 227), so the gain is not verbosity feeding a lenient judge.

Temporal slipped 1.7 points (one question). Within noise at n=61; noted rather than explained.

## Rejection counts after the relaxed guard

subject_mismatch 61, weak_quote 30 (from 33), subject_unresolved 27, quote-not-found 1. The
relaxation recovered 3 facts out of 33 — far less than the audit's 8-of-10 suggested. The audit
sample was therefore not representative: the guard was less harmful than the sample implied, and
relaxing it was correct but low-value.

## Process defect: result files collide across phases

Phase 9 re-ran the identical scope as phase 8, so `save_results` overwrote phase 8's evidence
files. The numbers survived only because phase 8 had been committed to git. That is luck, not
design. Fixed: result filenames now carry a UTC time stamp, so two runs of the same scope cannot
overwrite each other.

## Where the project stands

Cairn is +24 points over full context at 1/10th the tokens, and +32 points over naive chunk-RAG.
The thesis — cited compiled memory beats raw transcript and chunk retrieval on cost-adjusted
recall — is now measured on 150 questions, not asserted. Remaining weaknesses are commonsense
(63.6% vs 90.9% for naive_rag) and 21 answering failures that survive a brief containing the gold
support.

Further accuracy tuning is now diminishing returns. The larger gap to a usable open-source
project is surface: there is no CLI, no MCP server, no LICENSE and no install path.
