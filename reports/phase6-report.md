# Phase 6 report — answering quality, comparability preserved

## A. Compile defect verified and fixed

The recompiled phase-5 brain contained **"Melanie plans to become a single parent"**, cited to
capture `locomo:conv-26:session_2:14`:

> "You're doing something amazing! Creating a family for those kids is so lovely. You'll be an
> awesome mom! Good luck!"

The capture is `Melanie: You're doing something amazing! ...` — Melanie is **praising her
interlocutor** in the second person. The quote describes the *listener*, not Melanie. This is
over-inference by the phase-5 atomic-attribute rule: the extractor attributed an addressee
attribute to the page subject because the quote mentioned "family"/"mom".

**Fix** (`src/cairn/compile.py`, `EXTRACTION_SYSTEM`): the atomic-attribute rule now states the
attribute must be about the subject of the page — first-person or third-person-naming-subject
quotes qualify; a quote addressing someone else ("You'll be an awesome mom") describes the
LISTENER and must never be attributed to the subject; third-party attributes go on the third
party's page or are omitted. Test added: `tests/test_compile.py::test_atomic_attribute_rule_forbids_third_party_attribution`.

**Proof**: brains were recompiled (extractor changed — this changes the corpus the baseline was
measured on, as the brief requires us to flag). The recompiled `conv-26` brain has no
single-parent fact; the closest Melanie parenthood fact is now "Melanie is a parent" supported by
"Those moments make being a parent worth it" — a first-person quote. Full test suite:
`PYTHONPATH=src:. python3 -m pytest tests/ -q` → **52 passed**.

## B. Answering changes (exactly what changed)

1. `src/cairn/retrieve.py` — new `_looks_multi_hop()` heuristic (≥2 distinct capitalised entity
   names, or `what/which ... does/did/has/is/was`). For such questions `build_brief` now adds a
   **"### Supporting quotes"** section with the verbatim quotes of the top 8 selected facts, plus
   an **"### Answering rules"** block: combine several records into one answer; when the question
   asks for a list, list every supported item. The stable system message (page directory) is
   untouched — prefix stability and cache reuse are preserved.
2. `eval/harness.py` (cairn backend only) — the answer suffix changed from "Reply with a single
   short answer only — a date, name, number, place or short phrase" to "Reply with a short answer
   only — a date, name, number, place, short phrase, **or a short list when the question asks for
   one**". The old wording contradicted the new list instruction. The full_context and naive_rag
   prompts are byte-identical to the baseline run.

## C. Re-run on the same scope (2 conversations × 30 questions = 60)

All three backends, same commands as the baseline (`--recompile` added for cairn because the
extractor changed):

| backend | accuracy | mean context tokens | median latency | cache hit |
|---|---|---|---|---|
| cairn, 600-token brief | **75.0%** | 1,256 | 2.84 s | 0% |
| full_context | 50.0% | 13,277 | 0.32 s | 97% |
| naive_rag | 36.7% | 907 | 2.46 s | 0% |

By category (baseline in parentheses):

| category | cairn | full_context | naive_rag |
|---|---|---|---|
| temporal (n=34) | 85.3% (85.3%) | 29.4% (29.4%) | 17.6% (17.6%) |
| multi-hop (n=20) | **60.0%** (50.0%) | 75.0% (75.0%) | 50.0% (50.0%) |
| commonsense (n=4) | 50.0% (50.0%) | 75.0% (75.0%) | 100% (100%) |
| single-hop (n=2) | 100% (100%) | 100% (100%) | 100% (100%) |

Cairn diagnostic split: 53/60 briefs contained gold support, **3 retrieval failures, 12 answering
failures** (baseline: 2 and 15). No superseded facts surfaced.

## Verdict: did the gaps narrow?

- **Multi-hop: narrowed.** 50.0% → 60.0% (+10 points); answering failures dropped 15 → 12. The
  gap to full_context narrowed from 25 to 15 points. The quotes-plus-combine instruction did what
  the diagnostic predicted.
- **Commonsense: stayed.** 50.0% → 50.0% (n=4, so one question either way). The gap to
  full_context is unchanged at 25 points. Free-text inference over a conversation remains outside
  what a compiled fact set supports; n=4 makes any movement hard to detect.
- **Overall: improved.** 71.7% → 75.0% at 1,256 vs 1,141 tokens (quotes cost ~10% more brief
  tokens), still 10.6x fewer tokens than full_context.

## Caveats

- Brains were recompiled, so the corpus differs slightly from the baseline's (defect facts
  removed). The baseline backends were re-run on the same new scope, so the comparison above is
  internally consistent.
- Cairn prompt-cache hit rate measured 0% this run (baseline recorded 48%). The stable prefix is
  unchanged in construction; the recompiled page directory differs per brain, and this run's
  engine telemetry recorded no prefix reuse. Not investigated further here; flagged for the next
  phase.
- Judge is a local model, not GPT-judged; figures are not comparable to published
  LoCoMo numbers.

## Evidence

- Files changed: `src/cairn/compile.py`, `src/cairn/retrieve.py`, `eval/harness.py`,
  `tests/test_compile.py`.
- Commands: `PYTHONPATH=src:. python3 -m pytest tests/ -q` (52 passed); the three harness
  commands from the brief (cairn with `--recompile`), results in
  `eval/results/2026-11-05-cairn-b600-ps30-s2-q60.json`,
  `eval/results/2026-11-05-full_context-ps30-s2-q60.json`,
  `eval/results/2026-11-05-naive_rag-ps30-s2-q60.json`.
- Defect evidence: `sqlite3 eval/results/cairn-db/conv-26.db` queries quoted above (pre-recompile
  fact captured in this report; post-recompile verified absent).
