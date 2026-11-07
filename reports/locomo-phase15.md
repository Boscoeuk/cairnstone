# LoCoMo 150-question re-measure at the phase-16 HEAD (Tes, 2026-11-07)

Card: t_f480c1af. Label: **LOCAL-JUDGED**. This is a like-for-like re-measure, not a new
experiment. Settings are unchanged; only the code differs.

## Verdict

- **78.0% does not hold as a number for the current code. It does hold within noise.** At
  `fe71ff1` cairnstone scores **115/150 = 76.7%** (Wilson 95% 69.3–82.7). The 2026-11-06 baseline
  was 117/150 = 78.0% (Wilson 70.7–83.9). Per row: 12 lost, 10 gained, exact McNemar **p = 0.83**.
  The −1.3-point change is noise at n=150, and you cannot read it as a regression or a win.
- **README's sentence is not true as written.** "Recompiled and re-measured on the current code"
  describes code from before phase 13 (src ≈ `36257e0`). Phases 13–16 have changed `src/` since then.
  The README is updated (see the end of this report).

## What was run

- HEAD: `fe71ff177486d82b416e9bef664845b91565ec66` (phase 16, contains phase 15). Exported with
  `git archive fe71ff1` to a clean directory outside the repo, so the compile caches and the result
  could not touch the working tree:
  `<run-dir>` = a scratch directory on the measuring Mac. `SOURCE_COMMIT`, `CMD.txt`, `run.log` and the
  dataset hash are kept there.
- Dataset: `eval/datasets/locomo10.json`, sha256
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Answerer and compile/extraction: `glm-5.3-flash` on `127.0.0.1:8460`, the harness and
  `LLMClient` defaults, unchanged. Endpoint `/health` reported `glm-5.3-flash`.
- Judge: the same local route as on 2026-11-06, the `:8889` endpoint on the second local node. That
  baseline JSON was first committed with the route's real model id (`de140d5`/`cff4f23`).
  `3423565`/`64d5be5` later renamed the label to `local-judge` for the public repo, and the
  endpoint now only accepts the real id. So `--judge-model <route-model-id>` is the same judge
  under its real name, not a change. The judge prompt and the strict verdict parsing are
  `eval/harness.py` at `fe71ff1`, byte-unchanged.
- Embeddings: `text-embedding-nomic-embed-text-v1.5` on `127.0.0.1:1234` (harness default).
- Command (the harness's judge URL default is `127.0.0.1:8000`, which nothing listens on here, so
  the URL was set by environment; the model id is set by flag):

```
CAIRN_JUDGE_URL=http://<lan-node>:8889/v1 PYTHONPATH=src:. python3 -m eval.harness \
  --backend cairnstone --limit 2 --questions-per-sample 75 --max-questions 150 \
  --brief-budget 600 --recompile --judge-model <route-model-id>
```

- Compile output: conv-26 419 captures → 432 facts (baseline 421), 7 pages (6), 18 dupes linked
  (19), 0 superseded. conv-30 369 → 371 facts (376), 7 pages (6), 23 dupes (25), 0 superseded.
- Result: `eval/results/2026-11-07-cairnstone-b600-ps75-s2-q150-195905Z.json` (1,861.5 s wall).
  It was written in the run directory, not committed here. Moving it into the repo is a separate
  decision, because this card authorises only this report and the README paragraph.

## Numbers

| | baseline 2026-11-06 (`130032Z`) | re-measure at `fe71ff1` (`195905Z`) |
|---|---|---|
| n | 150 | 150 |
| accuracy | 78.0% (117) | **76.7% (115)** |
| mean context tokens | 1,276.2 | **1,274.8** |
| median latency | 2.893 s | **2.792 s** |
| mean latency | 3.265 s | 2.934 s |
| judge-ambiguous | 0 | 0 |
| latency outliers | 0 | 0 |
| gold support present in brief | 124 | 123 |
| retrieval failures | 13 | 13 |
| answering failures | 20 | 22 |
| non-temporal (89 q) | 63 (70.8%) | 61 (68.5%) |

By category:

| category | n | baseline | fe71ff1 | lost / gained |
|---|---|---|---|---|
| temporal | 61 | 88.5% | 88.5% | 2 / 2 |
| multi-hop | 40 | 70.0% | **65.0%** | 6 / 4 |
| single-hop | 38 | 73.7% | 73.7% | 3 / 3 |
| commonsense | 11 | 63.6% | 63.6% | 1 / 1 |

Row-level, matched on (sample_id, question), 150/150 rows paired: both correct 105, lost 12,
gained 10, both wrong 23. Exact two-sided McNemar on 12 vs 10: p = 0.83. 69/150 predictions
are byte-identical. The compiled brains changed (fact counts above), and that accounts for at
least some of the churn. Compile and answer both run at temperature 0. I did not measure how much
churn a same-code recompile would produce on this route, so code effect and run-to-run variance are
**not separated** here (unverified).

The only category that moved is multi-hop: −2 net, 6 lost / 4 gained. Most of the lost rows are
list answers that dropped one item ("Painting and running" against gold "Running, pottery";
"Mountains, beach, and with Caroline"). The gained rows are list answers that now carry the
missing item ("Violin and clarinet"). This is churn in which facts make the 600-token brief, not a
systematic loss. At n=40, ±2 rows is noise.

## LongMemEval S (20 questions, `cf34732`)

Measured before phase 15: `reports/longmemeval-result.md` caveat 1 says the run started before
`9e8191f`. It was therefore re-run at `fe71ff1` with the same command and seed. See the section below.

_Re-run in progress at the time of this commit; result to follow in a later commit._

## README

The sentence "recompiled and re-measured on the current code (2026-11-06 …)" was false. The
README's existing figures were kept unchanged (this card is read-only on measured numbers). The
provenance line was reworded to say what was measured on which code, and to state the `fe71ff1`
re-measure. The other derived figures in that section (24.7-point headline, 63/89 non-temporal,
category wins) are 2026-11-06 figures and are now labelled as such by that line.

## Unverified

- The exact baseline code. Its result was written at 13:00:32Z after a ~31-minute run, so `src`
  was `36257e0`–`245bbbf` (one 1-line `retrieve.py` difference between them). Which of the two ran
  was not proven.
- That the `:8889` backend weights are identical to 2026-11-06. It is the same route and the same
  DS-V4.1-Flash production model. The serving process was started
  2026-11-07 02:29 (node clock), so the judge is the same model but not the same
  process.
- Baselines (full context, naive chunk-RAG) were not re-run. They do not use the compiler.
- The test suite was not run as part of this card.
