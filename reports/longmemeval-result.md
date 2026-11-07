# LongMemEval S — measured result

Date: 2026-11-07. Harness: `eval/longmemeval/lme_eval.py`. Dataset: `eval/datasets/longmemeval_s_cleaned.json`
(500 questions, six types, haystacks ~48 sessions / ~105k tokens). Result file:
`eval/results/longmemeval-s-600-20q-20261107-162311Z.json`. Label: **LOCAL-JUDGED** (local judge).

Selection: 20 questions stratified across the six types, seed `20261106`, 600-token brief budget, 5
questions additionally run with full context. Deterministic and reproducible.

## Result

| backend | correct | accuracy | mean prompt tokens |
|---|---|---|---|
| cairnstone | 13/20 | 65.0% | 2,760 |
| keyword | 12/20 | 60.0% | 8,097 |
| full context | 2/5 | 40.0% | 104,949 |

By type (cairnstone / keyword / full context):

| type | n | cairnstone | keyword | full context |
|---|---|---|---|---|
| knowledge-update | 3 | 33.3% | 33.3% | 33.3% |
| multi-session | 5 | 40.0% | 40.0% | 50.0% |
| single-session-assistant | 2 | 50.0% | 100.0% | — |
| single-session-preference | 2 | 100% | 100% | — |
| single-session-user | 3 | 100% | 66.7% | — |
| temporal-reasoning | 5 | 80.0% | 60.0% | — |

Median latency 12.6 s, 3 latency outliers (one 261.7 s — a full-context question with a 105k-token
prompt; keyword's slowest was 267.9 s).

## Paired comparison — not a win

| | count |
|---|---|
| both correct | 9 |
| cairnstone only | 4 |
| keyword only | 3 |
| both wrong | 4 |

Discordant pairs 4 vs 3, exact McNemar **p = 1.0**. Cairnstone and keyword retrieval are at parity on
this sample. The defensible claim is the cost one: cairnstone reached the same accuracy with **2,760
prompt tokens against keyword's 8,097** (34%) and **2.6% of full context's 104,949**.

## What this says

- Full context is the worst backend here (2/5) despite 105k tokens per question. Same direction as
  LoCoMo: a large haystack does not improve answering, it dilutes it.
- Knowledge-update is the weakest type for every backend (1/3 each). That is the type the
  consolidation work targets, and these questions are the ones a nightly pass would have to get
  right. 3 questions is far too few to claim anything.
- Multi-session: cairnstone 2/5 vs keyword 2/5 vs full context 1/2.
- n=20 is small. Direction is honest but the interval is wide: 65% at n=20 is ±21 points at 95%.

## Caveats that must travel with the number

1. **Measured on pre-phase-15 code.** The run was launched before commit `9e8191f`. Phase 15 changes
   consolidation only (canonical choice, timestamp normalisation, slot keys), not extraction or
   retrieval ranking, so the figure is representative but not literally HEAD.
2. **The brief budget was not respected in the prompt.** A 600-token budget produced a mean 2,760
   prompt tokens, because supporting quotes and dialogue-context windows are appended after
   selection and are not counted against it. The reported token figures are the real prompt sizes,
   so the comparison is fair — but "budget 600" does not mean "600-token prompt".
3. **Local judge.** One local model graded every answer; no independent adjudication was done for
   this set (unlike the dogfood eval, where three readings disagreed on 5 of 40 verdicts).
4. **No independent review yet.** Tes has not reviewed this result. Treat it as provisional.

## Not claimed

- That cairnstone beats keyword retrieval on LongMemEval. It does not, at this n.
- That cairnstone beats full context. It does on this sample (13/20 vs 2/5) but full context ran only
  5 questions.
- Any improvement attributable to phase 15.
