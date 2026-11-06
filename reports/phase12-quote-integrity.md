# Phase 12 — quote redaction export and integrity evidence

Review gate: this commit is submitted to independent review on card `t_2c5d1028` (reviewer: Tes)
before it is pushed, and the SHA that reaches public main is the one that review approved. The
report is accurate both before and after the push.

## What this commit does

`eval/dogfood/quote_export.py` is the production redaction function. It re-derives every citation
quote in `eval/dogfood/results.json` from the source database (`facts.quote`, which is byte-equal to
`captures.content[span_start:span_end]`), replaces each machine-local literal with a bracketed
marker from a closed set, sets `redacted: true`, and records one `{marker, kind, reason}` entry **per
marker occurrence**. The `redactions` array carries no original value, so it cannot recover the
private literal.

Counts, measured by running the function over the export:

| kind | marker | entries | records | facts |
|---|---|---|---|---|
| address | `[redacted address]` | 6 | 6 | 5 |
| path | `[redacted path]` | 5 | 5 | 4 |
| model label | `[redacted model label]` | 5 | 5 | 5 |
| route label | `[redacted route label]` | 8 | 7 | 6 |
| tool name | `[redacted tool name]` | 7 | 7 | 5 |
| agent name | `[redacted agent name]` | 2 | 2 | 2 |
| **total** | — | **33** | **26** | **22** |

The totals are 26 records, 22 distinct facts and **33 entries**, not 32: fact 250 carries two
route-label markers and therefore two entries. Six records carry two kinds each, which is why the
per-kind record counts sum to more than 26.

The redaction set is exactly the set of literals the publication scrub removed from this file. Tokens
the scrub judged public stay verbatim: the loopback address, the repo-relative working directory, the
scratch path, the product and publish-hook names, the published weights label, and the upstream
author's name. Nothing else in the export changed; the 285 untouched citation records are byte-equal
to their stored source quotes.

## Where the literal rules live

`eval/dogfood/quote_export.py` is public, so it does not spell any private literal out. It carries
only the closed marker set, the fixed reasons, `MARKER_RE` and the redaction engine. The six regexes
that match the private values live in `eval/dogfood/redaction_rules.local.json`, which sits beside
`eval/dogfood/session.db` and is gitignored, as a JSON list of `{"kind": ..., "pattern": ...}`
entries whose kinds must be keys of the marker set. The export and the local byte-integrity test load
that file; a machine without it can still run the CI structural test. The public tree therefore
contains no network address, no account path, no model alias, no route alias, no harness name and no
agent name — not even inside a regex.

## The 26 redacted records

Span offsets are into the capture named by the record's `source_ref`. No literals appear in this
table.

| record | fact id | span | kinds |
|---|---|---|---|
| q04 | 37 | 11–93 | tool name |
| q07 | 1273 | 11–432 | tool name |
| q09 | 226 | 16–95 | route label |
| q11 | 1525 | 473–682 | path |
| q12 | 75 | 927–971 | model label |
| q12 | 147 | 63–250 | address, route label |
| q12 | 250 | 553–667 | model label, route label, route label |
| q12 | 257 | 626–713 | model label |
| q12 | 619 | 58–245 | address, route label |
| q12 | 811 | 709–789 | model label |
| q12 | 1140 | 58–245 | address, route label |
| q12 | 1368 | 1213–1361 | address, route label |
| q12 | 1538 | 835–915 | model label |
| q13 | 1356 | 222–410 | tool name |
| q13 | 1536 | 542–682 | path |
| q16 | 784 | 1104–1240 | path |
| q16 | 1027 | 68–125 | agent name |
| q16 | 1335 | 616–732 | agent name |
| q16 | 1368 | 1213–1361 | address, route label |
| q17 | 1273 | 11–432 | tool name |
| q18 | 1273 | 11–432 | tool name |
| q19 | 1152 | 1101–1202 | tool name |
| q20 | 1262 | 228–506 | tool name |
| q20 | 1371 | 96–283 | path |
| q20 | 1469 | 421–762 | address |
| q20 | 1536 | 542–682 | path |

Three facts appear in more than one question's citations (1273 in q07/q17/q18, 1368 in q12/q16,
1536 in q13/q20); each citation is a separate record with its own entry list, which is why records
outnumber facts.

## Test (b) — local byte integrity, real output

`tests/test_quote_integrity.py::test_local_byte_integrity` needs two gitignored, machine-local inputs:
`eval/dogfood/session.db` (the source database) and `eval/dogfood/redaction_rules.local.json` (the
literal rules). Where either is absent it skips with a reason that names the missing file, which is
what happens in a fresh clone or CI. Run locally, against the database the export was generated from:

```
$ python3 -m pytest -q -s tests/test_quote_integrity.py::test_local_byte_integrity
byte-integrity: 311 citation records match their session.db spans; 26 are redacted with 33 entries
.
1 passed in 0.01s
```

In a fresh clone of this commit both inputs are absent and the test reports:

```
$ python3 -m pytest -q -rs tests/test_quote_integrity.py
SKIPPED [1] tests/test_quote_integrity.py:113: gitignored machine-local inputs absent (fresh clone/CI): eval/dogfood/session.db, eval/dogfood/redaction_rules.local.json; the local byte-integrity check needs both the source database and the literal rules file
```

(The verbose header line, which prints the absolute checkout path, is elided here because the
checkout path is a machine-local literal; the rest is verbatim.)

The test proves, for all 311 citation records, that the stored quote is byte-equal to
`captures.content[span_start:span_end]`, that the exported quote is exactly
`quote_export.redact(...)` of that source quote, and that the exported `redactions` array equals the
entries the function returns.

## Test (a) — CI structural test

`tests/test_quote_integrity.py::test_export_structure` runs wherever the export exists, including CI.
It rejects any bracketed marker outside the closed set, requires each entry to carry exactly the keys
`marker`, `kind` and `reason`, and compares the multiset of markers in the quote with the multiset of
entry markers, so a per-occurrence gap such as fact 250's would fail. It also asserts the measured
totals above (26 / 22 / 33), so a future export cannot silently lose a redaction.

## D8 — speaker-resolution fix included

The brief allowed the speaker-resolution fix to be F's parent only if the reviewer had approved
`t_fb1af34f` (board `cairnstone`) before this commit. That card is now **done** (approved), and public
main already carries the fix: F's parent is public main itself, so the freeze is a direct
fast-forward and Phase 12's compiler measurements are taken **with** the speaker-resolution fix
present.

## Commit identity

The repository carries no repo-wide `user.name`/`user.email`; it sets `user.useConfigOnly true`, so a
commit made without an explicit identity fails rather than inheriting the machine account. F is
authored with an explicit agent identity on the commit itself. The earlier commits that had inherited
the machine account were re-authored to their real author before they were pushed, and F fast-forwards
on top of them.
