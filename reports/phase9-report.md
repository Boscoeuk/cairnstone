# Phase 9 — answerer calibration and corpus refresh

## Verdict

**Single-hop improved: 68.4% → 73.7%** (n=38). **The overall figure rose: 76.0% → 77.3%**
(n=150). Cairn remains ahead of full_context (53.3%) and naive_rag (45.3%) at ~1/10th the
tokens.

## A. Refusal instruction calibration

Changed the volatile answer suffix in `eval/harness.py` (CairnBackend.ask) so that:

- any record mentioning the question's subject counts as answering, even when the phrasing
  differs from the question;
- "Not recorded" is reserved for when **no** record mentions the subject;
- several answering records are combined, and what someone designed/wanted/liked/did gets
  every supported item listed, not one pick;
- the answer stays a short phrase or short list, no preamble.

This is a prompt change in the shared answer path, so it applies to all backends; all three
were re-run.

## B. Corpus recompile with the relaxed weak_quote guard

`--recompile` applied the current extractor to the eval corpus. Rejection counts by reason
(phase 8 pre-relaxation baseline in parentheses):

| reason | conv-26 | conv-30 | total | (phase 8) |
|---|---|---|---|---|
| subject_mismatch | 18 | 43 | 61 | (61) |
| weak_quote | 20 | 10 | 30 | (33) |
| subject_unresolved | 17 | 10 | 27 | (27) |
| quote not found in capture | 0 | 1 | 1 | (1) |

weak_quote rejections fell 33 → 30; the other reasons are unchanged, matching the phase-8
audit. 0 failed captures; 428 + 382 facts accepted.

## C. Results at n=150 (conv-26 75, conv-30 75)

| backend | accuracy | mean tokens | median latency (s) |
|---|---|---|---|
| **cairn** | **77.3%** | 1,276 | 2.83 |
| full_context | 53.3% | 13,278 | 2.73 |
| naive_rag | 45.3% | 932 | 2.71 |

Cairn by category (n per cell):

| category | n | cairn | full_context | naive_rag |
|---|---|---|---|---|
| temporal | 61 | 88.5% | 32.8% | 26.2% |
| multi-hop | 40 | 67.5% | 57.5% | 32.5% |
| single-hop | 38 | **73.7%** | 76.3% | 76.3% |
| commonsense | 11 | 63.6% | 72.7% | 90.9% |

Diagnostic split (cairn, n=150): 13 retrieval failures, 21 answering failures
(124/150 rows had gold support present). "Not recorded" answers: **9 of 150**.

## Reading

- Single-hop improved +5.3 points (68.4% → 73.7%) and now sits within 2.6 points of the
  baselines' 76.3% instead of 7.9 points below. The refusal cluster from the phase-8 audit
  (dance style, store findings, entrepreneurial comparison) is addressed by the calibration.
- Overall rose 76.0% → 77.3%; the ranking and margins over the baselines are unchanged.
- Commonsense (63.6% vs naive_rag 90.9%, n=11) remains the weakest category — carried
  forward from phase 8, still too small to conclude from.

## Evidence

- `eval/harness.py` — calibrated instruction (only change).
- `RAN`: the three harness commands from the brief, all exit 0.
- Results: `eval/results/2026-11-05-cairn-b600-ps75-s2-q150.json`,
  `eval/results/2026-11-05-full_context-ps75-s2-q150.json`,
  `eval/results/2026-11-05-naive_rag-ps75-s2-q150.json`.
- Nothing unverified beyond what the runs themselves show.
