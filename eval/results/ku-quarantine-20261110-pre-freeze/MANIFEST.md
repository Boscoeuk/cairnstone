# Quarantine — pre-freeze KU artifacts (2026-11-10)

Everything in this directory was produced **before** the phase-17 freeze (no frozen code SHA, no
committed config, two arms only, consolidation in place with `max_mutation_rate=None`, old
full-pool sampling). It is kept as evidence but **must not be reused** by the phase-17 run. The
harness refuses any brain without a matching `<qid>.meta.json` provenance sidecar (§P8.8 of
`docs/phase17-brief.md`), so these files cannot silently re-enter the experiment.

## What was stopped

`eval/longmemeval/ku_paired.py --questions 20 --budget 600 --seed 20261106 --out
eval/results/ku-paired-20q.json --resume`, pid **45392**, started 2026-11-10 16:22 from Polly's
interactive session on the **unfrozen** harness. It overlapped 19 of the 74 eligible ids and 7 of the
20 pilot ids, and it held `:8460`, which would fail gate §B8.1. Killed with SIGTERM at 16:29 before
any answer or verdict was written; no `ku-paired-20q.json` was produced.

## Files (moved, not deleted)

| file | sha256 | size | what it is |
|---|---|---|---|
| `71315a70.db` | `b656057973a5ed83b6d37dfc23991c8be77c768f98ddf450dee35579ef5c92c3` | 2,785,280 | the 1-question smoke brain (228 captures / 388 facts, compiled 15:50–16:19). `71315a70` is excluded from the 74 and is recompiled at the frozen SHA for the §P5 gate. |
| `71315a70.db-shm`, `71315a70.db-wal` | `fd4c9fda…9389eb`, `e3b0c442…b855` (empty) | 32,768 / 0 | SQLite sidecars of the above; the WAL is empty, so no data is held there. |
| `1cea1afa.tmp`, `1cea1afa.tmp-shm`, `1cea1afa.tmp-wal` | `10c7ed80…e6836`, `7dd62f47…b4943`, `c548112c…6c7fee` | 790,528 / 32,768 / 4,128,272 | partial brain of the stray run: all 232 captures built, 44 of the extraction calls done, no consolidation. Incomplete, therefore not reusable. |
| `ku-paired-smoke.json` | `1c8bd0e0f781c43d2337df79fb1409d6e3feedf696b2e32b1971831fc4ae2d1c` | 3,219 | the 1-question smoke result (two arms, no rate). Continuity evidence only — `71315a70` is excluded from the 74. |

Counts were read with `sqlite3` against the files after the run stopped (not from the logs).

## Why move rather than delete

The smoke brain is the only pre-freeze example of the compile path, and `71315a70.db` is the file the
old citation figure (1,640/1,640 from the 11-07 `session.db`) can be compared against. Moving keeps
the evidence while making `eval/results/ku-db/` contain **only** frozen-SHA brains.

`eval/longmemeval/ku-run.log` and `eval/longmemeval/ku-smoke.log` stay where they are: they are logs,
not brains, and no gate reads them.
