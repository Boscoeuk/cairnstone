# Phase 17 D5 fix report (position numbers after progress labels)

Author: Polly. Date: 2026-11-10. Card: `t_92e125ff`. Fixes Tes review 6 §6 D5
(`reports/tes-review-6.md`). Status: **PROVISIONAL: awaiting Tes (review 7)**.

Pushed: `341f11e..25c674f` on `origin/main` (fast-forward). CI run
`42884486306` on `25c674f`: success (pytest 3.10/3.12, mcp import check).

Worktrees used: the card workspace `t_92e125ff/wt` (branch `p17-d5`, fixed) and
`t_92e125ff/wt-base` (detached at `341f11e`, baseline). The 27 probe DBs were copied into both
worktrees from the main checkout (they are gitignored); originals were sha256-checked before and
after and were never opened read-write.

## Change

`src/cairnstone/compile.py`: eleven progress nouns removed from `_IDENTIFIER_LABELS` —
`page episode level chapter season grade round stage step unit volume`. Everything else on the
list is unchanged (`phase conv sample budget n v version tier port pid issue id pr section
question task ticket sprint wave epoch model commit class batch trial arm condition`), and no
position-marker rule was added, so the label list itself stays load-bearing for the mutant check.

`tests/test_phase17.py`: five new tests (+124 lines, additive only, no existing test touched):

| test | locks down |
|---|---|
| `test_d5_position_after_a_progress_label_supersedes` | the 10 review-6 D5 rows supersede |
| `test_d5_part_b_position_shapes_supersede` | the 3 frozen Part B shapes (`184da446`, `72e3ee87`, `9bbe84a2`) supersede |
| `test_d5_identifier_keying_is_unchanged` | Phase 1/2, conv-26/30, budget 600/1200, b600/b1200, Chapter 2/3 key apart; label-list membership asserted |
| `test_d5_hyphen_joined_digits_after_an_unlisted_label_stay_in_the_key` | gap G1 (`invoice-4471` vs `invoice-4472`) |
| `test_d5_noun_modifier_is_the_only_reason_a_status_word_is_rejected` | gap G2 ("single-handedly") |

`docs/phase17-d5-brief.md`: the brief given to the implementing worker.

## Acceptance evidence

1. **D5 table and Part B shapes.** `edge6.py` (Tes's own script, run by me) on the fixed tree:
   A section **10/10 superseded**, `sup=1 flag=0` on every row, including "week" which already
   superseded at `341f11e`. At the baseline `341f11e` the same script gave 1/10.
   `ku_labels6.py` (Tes's Part B paraphrase script) on the fixed tree: **3/3 superseded**
   (`184da446`, `72e3ee87`, `9bbe84a2`), `sup=1 flag=0`; at baseline 0/3.
2. **Phase 1/Phase 2, conv-26/conv-30, budget 600, b600.** `keydump.py` prints six pairs
   **APART/APART**: `phase 1 accepted after correction` vs `phase 2 accepted after correction`;
   `conv 26 baseline` vs `conv 30 baseline`; `cairn at budget 600 scored accuracy at token` vs
   `cairn at budget 1200 scored accuracy at token`; `b600 run` vs `b1200 run`; plus the two
   below. The F3 phase/budget tests still pass unchanged.
3. **Real corpus chapter facts.** In `eval/results/lme-db/5d3d2817.db`, facts 81 and 82
   ("…write Chapter 2: A League of Extraordinary Talent…" / "…Chapter 3: Rising to the
   Challenge…") key apart after the fix (`chapter league extraordinary talent` vs `chapter
   rising to challenge`) and both stay **active** after two consolidation passes (1 duplicate
   link, 0 supersessions, 0 flags — same as baseline).
4. **Mutant restoring the current label list.** `mutants_d5.py`
   `D5_restore_341f11e_label_list` (re-inserts the exact `341f11e` frozenset) →
   **3 failed, 169 passed, 1 skipped**, failing
   `test_d5_position_after_a_progress_label_supersedes`,
   `test_d5_part_b_position_shapes_supersede` and
   `test_d5_identifier_keying_is_unchanged`. Two further mutants close the G1/G2 gaps:
   `D1_no_hyphen_rule` → `test_d5_hyphen_joined_digits_after_an_unlisted_label_stay_in_the_key`
   fails (1 failed); `D2_no_modifier_check` →
   `test_d5_noun_modifier_is_the_only_reason_a_status_word_is_rejected` fails (1 failed).
   The file was restored and byte-compared after each mutant.
5. **27-DB probe, exact diff vs `341f11e`.** Baseline (`wt-base`, `341f11e`) reproduced Tes's
   numbers exactly: pass 1 **0 superseded / 13 flagged / 39 duplicates_linked**, pass 2 no-op on
   27/27, `diff_probe.py` → superseded 0 (0 cross-page), flags 13 (0 cross-page), dup rows changed
   61 — byte-identical to Tes's `dp-head.json` from review 6. Fixed tree (`wt`, `25c674f`):
   **identical** pass-1 totals, identical per-DB output, pass 2 no-op 27/27, and
   `diff dp-base.json dp-fixed.json` is empty. So the fix changes nothing on the current corpus —
   as predicted, none of these questions has a compiled brain in `lme-db` and the corpus has one
   `level` and seven `chapter` identifier hits.

**Blast radius on corpus keys** (`keyshift.py` over all 11,608 active facts in the 27 DBs):
13 facts change slot key, all of them the intended shape (chapter/step/level/grade numbers moving
from key to value). No fact changes status, no new flag, no duplicate change. The two chapter
facts above are among the 13 and still key apart.

## Suite

`env -i PATH=/usr/bin:/bin PYTHONPATH=src <repo>/.venv/bin/python -m pytest -q -p no:cacheprovider
tests/` on `25c674f`: **172 passed, 1 skipped** (167+5; the skip is the pre-existing one).
`-k d5`: 5 passed, 34 deselected. CI on the same sha is green.

## Non-blocking items closed in this pass

- G2: a test where the noun-modifier check is the only rejection ("The user is single-handedly
  running the bake sale"); the mutant shows it is load-bearing.
- G1: a hyphen-rule test with an unlisted label (`invoice-4471`/`invoice-4472`); the mutant shows
  the rule is load-bearing.

Still open, unchanged from review 6 and not in this card's scope: "dating <Name>" and
"got divorced last year" lose the relationship slot; past-tense "was single in college" retires a
current status; the D2 relative-pronoun check remains redundant.

## Publication

`publish-guard` blocked the first push on three `local-path` hits in `docs/phase17-d5-brief.md`
(same fingerprint `f77c2c89e85f02b5`). I reworded the three lines to use relative/`<repo>` paths
instead; **no allow entry was added**. The push then succeeded.

## Handoff notes

- **Hotspot:** `tests/test_phase17.py` (all phase-17 tests live in this one file) and
  `eval/longmemeval/ku_paired.py`.
- The harness worker (pid 40545, `ms-glm/glm-5.3-flash`) is still running in the main checkout
  `~/cairnstone`, whose local `main` is `b976d44` with dirty `ku_paired.py` / `lme_eval.py`. It did
  not touch this fix; its commit will need a rebase onto `25c674f` before it lands. I did not
  review that harness work.
- Part B was **not** started. `t_06130149` (Tes, review 7) is parented on this card and promotes
  on completion; `t_788a7752` (LoCoMo/LongMemEval re-measure) is gated behind it.

## Evidence files (attached to card `t_92e125ff`)

`edge6.py`, `ku_labels6.py`, `d5_check.py`, `keydump.py`, `keyshift.py`, `keyshift_diff.py`,
`mutants_d5.py`, `run_probe.py`, `diff_probe.py`, plus the outputs quoted above
(`base-probe6.out`, `fixed-probe6.out`, `dp-base.json`, `dp-fixed.json`, `keys-*.json`,
`mutants_d5.out`, `orig.sha256`).
