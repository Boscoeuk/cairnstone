# Phase 12 — dogfooding on a real transcript (PROVISIONAL: awaiting the reviewer review)

Ged has appointed the reviewer the independent reviewer for Cairnstone. Every number below is the maintainer's
reading of the evidence and is **not accepted** until the reviewer verifies it (Kanban task
`t_dd545ced`, board `cairnstone`).

## What was tested

The corpus is this profile's own Hermes session transcript — 366 captures, built by
`eval/dogfood/build_corpus.py` from `~/.hermes/state.db`. No curated reports were
used, so the brain had to recover facts from the raw work record.

Twenty questions with gold answers independently known from the project's reports
(`eval/dogfood/questions.json`), two backends answering with the same local model
(`glm-5.3-flash`): compiled memory (`retrieve.build_brief`, 600-token budget) and a keyword
baseline over the same raw captures (`dogfood_eval.py::keyword_retrieve`, top-3 chunks).

Compile result: 366 captures → **1,640 accepted facts, 300 rejected, 0 failed captures**, 306
duplicates linked, 25 superseded, 1,615 active facts across entity pages.

## The compile could not ingest a real transcript at all

The first run aborted after two captures: **80% of extracted facts rejected** (policy P2 ceiling
0.25). Root cause was not a threshold to raise — it was the phase-7 subject-resolution guard
assuming every subject is a person speaking in a turn. Agent transcripts break both assumptions:
speakers are role labels (`assistant`, `user`) and subjects are projects, phases, decisions and
tools, which is exactly what the README claims the compiler handles.

Fixed at the source in `src/cairnstone/compile.py`:

- Person-grammar checks now apply only when the quote actually contains first/second person. A
  quote with no person grammar is decided by whether it names a different person, sits in the
  subject's own turn, or defers to the weak-quote guard.
- A transcript role label is not a candidate subject, so it cannot contradict attribution.
- `locate()` now tolerates markdown emphasis, unicode dashes/quotes and case, mapping the match
  back to real capture offsets — the stored span is always real capture text, so the citation
  invariant is unchanged.

Measured on the same six captures: **rejection rate 80% → 10%** (36 accepted, 4 rejected).
Suite: 87 tests pass, including four new tests (entity subject accepted, entity subject rejected
when ungrounded, role speaker does not reject a grounded person fact, cosmetic quote match).

## Dogfood result — three readings, none authoritative

| reading | compiled memory | keyword baseline |
|---|---|---|
| automated judge (local-judge) | 16/20 (80%) | 11/20 (55%) |
| second model, blind to the project | 16/20 (80%) | 12/20 (60%) |
| the maintainer's own reading | 18/20 (90%) | 14/20 (70%) |

The direction is consistent across all three readings: compiled memory answers more of these
questions than keyword retrieval over the same transcript. The magnitude is not settled, and at
n=20 neither is significance (McNemar exact p ≈ 0.13 on the maintainer's reading, 6 discordant pairs to 1).

The graders disagree on 5 of 40 verdicts (q05, q07, q09, q10, q20). The automated judge is
therefore not reliable enough to be the sole arbiter — a finding about the judge, not about the
compiler. the maintainer wrote the questions and knows the answers, so her reading is not independent
either. This is precisely why the adjudication now goes to the reviewer.

### Failures worth naming

- **q01** ("what accuracy did the compiled backend reach on 150 questions?") — memory answered
  `45.3%` (the naive-RAG number) instead of `77.3%`. The brain holds several accuracy figures
  across phases and the question does not name a phase. Same interference class seen on LoCoMo.
- **q10** ("what did the first CI failure expose about the retriever?") — memory answered "the
  workflow didn't install pytest" (the first failure) instead of the retriever defect. Both are
  true statements in the transcript; retrieval picked the earlier, more superficial one.

## Open risk flagged to the reviewer

The README's headline claim (77.3% on 150 LoCoMo questions at 1,276 tokens vs 53.3% full
context) was measured **before** the compile change in commit `ad1cb64`. A re-run with
`--recompile` is in flight. If the number has moved, the README changes — the number does not.
