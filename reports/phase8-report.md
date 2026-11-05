# Phase 8 — inference support and a firmer sample

`DONE: Phase 8 complete — dialogue context for inference questions (A), weak_quote guard audited and relaxed (B), all three backends re-run at n=150 (C). 69 tests pass.`

## A. Dialogue context for multi-hop and commonsense questions

`retrieve.build_brief` (src/cairn/retrieve.py) now takes a `category` argument. For questions
classified `multi-hop` or `commonsense` it appends a `### Dialogue context` section to the
**volatile** message: for each selected fact, a bounded window of the cited capture's turn plus
the immediately preceding and following turn from the same conversation (captures are one turn
each; neighbours are resolved via the session index in `capture.source_ref`). Hard caps, as
specified: at most 3 windows (deduplicated by capture), at most `context_window_chars` = 600
characters per window (constant `_CONTEXT_WINDOW_CHARS` in retrieve.py; `config/policies.yml`
does not exist in the repo, so the default lives there until thresholds get a shared home).

- The stable system message is byte-identical with and without the section — verified on the
  real conv-26 brain and by `test_build_brief_prefix_is_question_independent` (still passing).
- The harness passes the question's category label through `CairnBackend.ask(..., category=...)`
  from `qa["category"]` via `CATEGORY_NAMES`. **Bug found and fixed during verification:** the
  first cairn run passed the raw integer category, which never matched the string labels, so
  the section silently never fired (mean brief tokens 903.7, identical to phase 7). After the
  fix the mean brief tokens rose to 1,027.6 (max 1,401) — the section was active in the
  reported run.
- When no category is supplied, the phase-6 multi-hop heuristic (`_looks_multi_hop`) decides,
  so the API degrades safely for callers without labels.

Tests: 5 new tests in tests/test_retrieve.py (category gating, commonsense, heuristic
fallback, 3-window cap, 600-char cap).

## B. weak_quote audit — 8 of 10 rejections were valid facts; guard relaxed

The phase-7 compile run did not persist its rejected proposals (only counts were printed), so
the audit regenerated them: `eval/audit_weak_quotes.py` re-ran the **unchanged** extractor over
the two eval conversations into scratch DBs (`eval/results/cairn-db/audit-*.db`) and recorded
every proposal the weak_quote guard rejected, with quote and subject. The fresh run produced
exactly **33** weak_quote rejections — matching phase 7's count
(eval/results/phase8-weak-quote-audit.json). The first 10 were audited against their full
captures:

| # | fact | quote (verbatim) | verdict |
|---|---|---|---|
| 0 | Melanie has children | "I'm swamped with the kids & work" | **valid lost** (kids→children) |
| 1 | Melanie has a family | "helps me stay present for my fam" | **valid lost** (fam→family) |
| 2 | Caroline is a foster parent caring for children | "I'll do my best to make sure these kids have a safe and loving home" | rejection right — "foster parent" is not in the quote |
| 3 | Mel supports Caroline | "Thanks, Mel! Your backing really means a lot." | **valid lost** (speaker Caroline thanking Mel) |
| 4 | Melanie is married | "I'm lucky to have my husband and kids; they keep me motivated." | **valid lost** (husband→married) |
| 5 | Melanie has children | same quote as #4 | **valid lost** (kids→children) |
| 6 | Melanie got married | "Congrats, Melanie! You both looked so great on your wedding day!" | **valid lost** |
| 7 | Melanie is married | "Looking forward to more happy years. Our family and moments make it all worth it." | rejection right — the quote alone does not state marriage |
| 8 | Melanie has a family (children) | "I just took my fam camping in the mountains" | **valid lost** (fam→family) |
| 9 | Caroline is trans | "…making a safe space for people like me" | **valid lost** (speaker groups herself with trans people; consistent with phase-7's verified "Caroline is transgender") |

**8 of 10 valid — far over the 2/10 threshold. Decision: relax the guard**, exactly as the
brief prescribed: `_weak_quote` (src/cairn/compile.py) now rejects only when the quote shares
no content token with the fact's text **and** does not mention the subject's name.

Effect, measured two ways:

- Deterministically, on all 33 recorded rejections: the relaxed guard would now accept **3 of
  33** (the quotes that name the subject: "Thanks, Mel!…", "Congrats, Melanie!…", "Wow Jon…").
- By re-running the compile with the relaxed guard into scratch DBs
  (`eval/rerun_relaxed_compile.py` → `eval/results/cairn-db/relaxed-*.db`): weak_quote
  rejections fell 33 → 30 (conv-26: 22→20, conv-30: 11→10), facts accepted rose 807 → 810.
  Other rejection categories unchanged (subject_mismatch 61, subject_unresolved 27, quote
  not found 1).

Honest limits: the relaxation recovers only the rejections where the quote names the subject
(3 of the 8 valid losses in the sample). The rest are pure paraphrases with no lexical anchor
(kids→children, fam→family, husband→married) and would need embedding or synonym matching —
not prescribed, not done. Residual risk: a quote that names the subject but is addressed *to*
them could now be attributed to them; the phase-7A subject guard still runs first and still
rejects grammatical-person mismatches, and the phase-7 rejection test
(`test_weak_quote_rejected`) still passes because its quote names nobody.

## C. The firmer sample — n=150, all three backends

Compilation was cached (the phase-7 corpus, unchanged — per the brief; the relaxed guard
applies to future compiles and was verified separately above). Commands run (exact):

```
PYTHONPATH=src:. python3 -m eval.harness --backend cairn --limit 2 --questions-per-sample 75 --max-questions 150 --brief-budget 600
PYTHONPATH=src:. python3 -m eval.harness --backend full_context --limit 2 --questions-per-sample 75 --max-questions 150
PYTHONPATH=src:. python3 -m eval.harness --backend naive_rag --limit 2 --questions-per-sample 75 --max-questions 150
```

(The cairn command was run twice: once before the category-plumbing bug in part A was caught,
once after. The table below is the fixed run; both result files are retained as evidence.)

### Accuracy by category (n=150, local judge)

| category | cairn phase 8 | cairn phase 7 (n=60) | full_context | naive_rag |
|---|---|---|---|---|
| temporal | **90.2%** (n=61) | 88.2% (n=34) | 32.8% (n=61) | 26.2% (n=61) |
| multi-hop | **67.5%** (n=40) | 65.0% (n=20) | 57.5% (n=40) | 32.5% (n=40) |
| commonsense | 54.5% (n=11) | 50.0% (n=4) | 72.7% (n=11) | 90.9% (n=11) |
| single-hop | 68.4% (n=38) | 100% (n=2) | 76.3% (n=38) | 76.3% (n=38) |
| **overall** | **76.0%** (n=150) | 78.3% (n=60) | 53.3% (n=150) | 45.3% (n=150) |

Cost and diagnostics (cairn): 1,204 mean context tokens (phase 7: 1,109), 1,028 mean brief
tokens, 2.64 s median latency, 0 latency outliers, 0 superseded facts surfaced. Retrieval/
answering split: 124/150 rows had gold support in the brief; **13 retrieval failures, 23
answering failures** (phase 7: 3 / 10 on n=60). full_context: 13,278 tokens, 0.33 s median,
98.7% cache hits. naive_rag: 932 tokens, 2.44 s median.

### Verdict: the larger sample **weakens the point estimate slightly, but does not overturn it**

- Cairn at n=150 is **76.0%** vs phase 7's 78.3% at n=60. The 95% binomial interval at n=150,
  p=0.76 is roughly ±6.8pp, so 78.3% is well inside it: the two measurements are statistically
  consistent, and the honest reading is "76% ± 7%, phase 7 confirmed within noise, point
  estimate a little lower".
- The ranking is unchanged and decisive: cairn 76.0% vs full_context 53.3% (+22.7pp) and
  naive_rag 45.3% (+30.7pp) on the same 150 questions.
- The phase-7 category story holds: temporal is cairn's strongest category (90.2%), and
  multi-hop improved with dialogue context (60.0% → 67.5% between the two cairn runs in this
  phase). Commonsense (54.5%) and single-hop (68.4%) remain the weak spots; single-hop's
  phase-7 100% was n=2 and was never a real claim. full_context still beats cairn on
  commonsense (72.7% vs 54.5%) — the raw transcript keeps an inference edge a flat fact set
  has not closed.

## Rules compliance

- Judge and extractor unchanged. The eval corpus was not recompiled; the relaxed guard was
  verified on scratch DBs only.
- Local only: all calls hit 127.0.0.1:8460 (answer), 127.0.0.1:8889 (judge),
  127.0.0.1:1234 (embeddings).
- Note: cairn's engine telemetry reported 0% prompt-cache hits, identical to phase 7 —
  pre-existing, not a phase-8 regression.

## Verification

`PYTHONPATH=src:. python3 -m pytest -q` → **69 passed** (67 before phase 8; +5 retrieval, +2
compile tests). Smoke evidence quoted inline above; all numbers in this report come from the
saved result JSONs in eval/results/ and the audit JSON.

## Files

- src/cairn/retrieve.py — dialogue-context helper, category gating, build_brief wiring
- src/cairn/compile.py — relaxed `_weak_quote` (phase 8B)
- eval/harness.py — category plumbing into `ask`/`build_brief`
- tests/test_retrieve.py, tests/test_compile.py — 7 new tests
- eval/audit_weak_quotes.py, eval/rerun_relaxed_compile.py — audit/re-run tools
- eval/results/phase8-weak-quote-audit.json — the 33 recorded rejections
- eval/results/2026-11-05-{cairn-b600,full_context,naive_rag}-ps75-s2-q150.json — run results
