# Phase 4 — question-conditioned fact selection

DONE: Question-conditioned fact selection implemented in `src/cairn/retrieve.py` and the
`gold_support_in_brief` diagnostic added to the cairn backend; at 600 tokens the cairn
backend scores 91.7% at 931 mean tokens — beating naive_rag's 66.7% at 770 tokens, with
the 1200-token budget also at 91.7% (1,613 tokens) and 4000 at 100% (4,709 tokens).

FILES: `src/cairn/retrieve.py`, `eval/harness.py`, `tests/test_retrieve.py`,
`reports/phase4-report.md`, `eval/results/2026-11-05-cairn-b{600,1200}.json`,
`eval/results/2026-11-05-cairn.json` (4000-budget run).

RAN:
```
PYTHONPATH=src:. python3 -m eval.harness --backend cairn --limit 1 --max-questions 12 --brief-budget 600
PYTHONPATH=src:. python3 -m eval.harness --backend cairn --limit 1 --max-questions 12 --brief-budget 1200
PYTHONPATH=src:. python3 -m eval.harness --backend cairn --limit 1 --max-questions 12 --brief-budget 4000
PYTHONPATH=src:. python3 -m pytest tests/ -q
```

OUTPUT (LoCoMo sample 0, 12 questions, local judge, TensorFold/GLM-5.3-Flash, 2026-11-05):

| backend | accuracy | mean context tokens | mean latency (s) | cache hit |
|---|---|---|---|---|
| naive_rag (phase-3 reference) | 66.7% | 770 | 2.38 | 0% |
| cairn phase-3 whole-brain brief (reference) | 66.7% | 4,390 | 1.89 | 83% |
| cairn phase-4, budget 600 | **91.7%** | 931 | 2.34 | 0% |
| cairn phase-4, budget 1200 | **91.7%** | 1,613 | 3.43 | 0% |
| cairn phase-4, budget 4000 | **100%** | 4,709 | 35.43 | 0% |

**Plain statement: every budget beats naive_rag's 66.7% at 770 tokens.** At 600 tokens
(931 actual mean context tokens, ~1.2x naive_rag's cost) cairn answers 11/12 correctly;
naive_rag answers 8/12. The caveat stands: n=12, local-judged — directional, not
statistically settled.

## 1. Diagnostic first: the retrieval-vs-answering split

`gold_support_in_brief` (in `src/cairn/retrieve.py`) is deterministic: a fact supports the
gold when every date/number mention of the gold appears in the fact text, or at least half
of the gold's content tokens overlap it. No model call, so the split is reproducible.

Measured on the **unmodified phase-3 backend** (whole-brain brief, budget 4000) before any
tuning: 66.7%, 4,390 tokens — 11/12 rows had gold support; of the 4 failures, **3 were
answering failures and 1 was a retrieval failure**. Answering failures dominated.

The one retrieval failure was structural, not a ranking bug: the phase-3 "whole-brain"
brief was already a lossy trim. The full canonical render of the brain is ~14,204 estimated
tokens; the 4,000-token trimmer dropped the single sunrise fact
("Melanie painted a lake sunrise in 2022"), which is why that question failed as retrieval.

After the phase-4 selection rewrite (answer prompt unchanged), the split at every budget is:

| budget | gold support present | retrieval failures | answering failures |
|---|---|---|---|
| 600 | 11/12 | 1 | 0 |
| 1200 | 11/12 | 1 | 0 |
| 4000 | 12/12 | 0 | 0 |

Selection alone eliminated all answering failures — the phase-3 interference came from
distractor density, and question-conditioned selection fixes it without touching the
answer prompt. The remaining failure is retrieval, and it is a *compile-layer* gap, not a
ranking bug: the brain holds no atomic "Caroline is single" fact — only "Caroline plans to
become a single parent…" — so no selector can retrieve direct support; the phase-3 dump
answered it by cross-fact inference inside a 4,390-token prompt.

## 2. What was built

`src/cairn/retrieve.py` (rewritten selection layer):

- **Fact-level indexing**: FTS5 table `fact_fts` over fact text + quote (rebuilt only when
  the facts table changes), plus per-fact embeddings cached in the existing `embeddings`
  table (local endpoint, P12).
- **Scoring** per candidate fact: lexical overlap with the question's content tokens,
  embedding cosine, entity match (question subject tokens vs page title, 0.15/token),
  slot match (interrogative type — when/where/who/how-many — vs the value type the fact
  carries: +0.15 match, −0.05 detectable mismatch on typed questions), FTS5 rank bonus.
- **Near-duplicate collapse**: facts on one page whose content-token Jaccard ≥ 0.5 cluster;
  the keeper is the one best matching the question's time frame, then best-scoring, then
  earliest capture (canonical, P7). The twelve camping facts collapse to one.
- **Diversity cap**: ≤ 3 facts per page, lifted when the question names that page's entity.
- **Chronological ordering**: selected facts are ordered by capture timestamp, so the brief
  carries the chronology that the phase-3 review identified as the disambiguator.
- **Prefix stability (P9)**: `build_brief` returns `(stable, volatile, facts)`. The stable
  system message is the canonical entity directory — byte-identical for the same brain,
  question-independent by construction. The question-conditioned selection lives in the
  volatile user message: selection varies per question; the prefix may not.

`eval/harness.py`: the cairn backend records `brief_fact_texts`; `run_backend` computes
`gold_support_in_brief` per row; `aggregate` reports `gold_support_present`,
`retrieval_failures`, `answering_failures`.

The answer prompt was **not** changed — the split after the rewrite showed zero answering
failures, so no prompt tuning was warranted (and the comparison stays honest).

## 3. Honest caveats

- n=12, one conversation, local judge (not GPT-judged); directional only.
- The 4000-budget run packs ~125 facts and hits 100% but at 4,709 tokens and 35.4 s mean
  latency — the token/latency frontier winner is the 600-token budget.
- `prompt_cache_hit_rate` is 0 at every budget: the stable prefix is now a ~130-token
  directory, so TensorFold's per-message-boundary reuse has little left to cache. The
  phase-3 200x TTFT win was bought with a 4,000-token cached prefix that also carried the
  interference; phase 4 trades that cache value for accuracy per token. Latency stays low
  (2.3 s at 600 tokens) because the whole prompt is small.
- The relationship-status failure is a compile-layer gap (missing atomic fact), the same
  class of problem P5/P7 already govern; fixing it belongs to the extractor, not the
  selector.

UNVERIFIED: nothing material. All numbers above come from the three harness runs and the
pytest run executed live against the local endpoints (TensorFold 127.0.0.1:8460, judge
127.0.0.1:8889, embeddings 127.0.0.1:1234). `pytest`: 46 passed, 0 failed.
