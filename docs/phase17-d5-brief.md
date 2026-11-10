# Phase 17 D5 brief: position numbers after progress labels must stay values

Card: `t_92e125ff`. Reviewer: Tes (`reports/tes-review-6.md`, §6 D5). Worktree: the
board's task workspace `t_92e125ff/wt`, branch `p17-d5`, at `341f11e`. Work only inside that
worktree.

## Outcome

Make a later *position* supersede an earlier one when the position number follows a progress
label noun ("on page 200" → "on page 220", "episode 10" → "episode 50", "level 100" →
"level 150"), without weakening any identifier keying that review-6 accepted.

## The defect

`_IDENTIFIER_LABELS` in `src/cairnstone/compile.py` (~line 1297) contains progress nouns, so
`_is_identifier_digit` keeps the number in the slot key. Two positions then key apart and the
older fact never supersedes. Reproduced at `341f11e`: 9 of Tes's 10 progress rows stay
`active`, and all 3 Part B shapes stay `active`.

## The fix (already decided — do not redesign it)

Remove exactly these eleven tokens from `_IDENTIFIER_LABELS`:

```
page episode level chapter season grade round stage step unit volume
```

Keep every other token exactly as it is, in particular: `phase conv sample budget n v version
tier port pid issue id pr section question task ticket sprint wave epoch model commit class
batch trial arm condition`.

Do **not** add position-marker detection (`on`/`at`/`in`/`to`/`reached`/`is`/…). The reviewer
requires that restoring the *current* label list makes the new tests fail, so the label list
itself must be the load-bearing mechanism. A marker rule would mask the mutant.

Add a short comment block above `_IDENTIFIER_LABELS` recording: phase 17 (D5) — progress nouns
were taken off the list because a position after them changes over time ("on page 120" →
"on page 310", "reached level 30" → "level 45"); those numbers are values, not names, so a later
position supersedes; `Chapter 2: …` / `Chapter 3: …` still key apart because the titles differ.

## Tests to add

Append a new section to `tests/test_phase17.py` (end of file, after the D3 tests). Reuse the
existing `db`, `_capture`, `_fact`, `_row` helpers; same page for both facts; timestamps
`2023-05-01T00:00:00+00:00` (older) and `2023-08-01T00:00:00+00:00` (newer).

1. `test_d5_position_after_a_progress_label_supersedes` — `@pytest.mark.parametrize` over these
   ten rows (Tes review 6 §6 D5 table):
   - "The user is on episode 5 of The Crown" → "The user is on episode 9 of The Crown"
   - "The user is on page 120 of Dune" → "The user is on page 310 of Dune"
   - "The user reached level 30 in Elden Ring" → "The user reached level 45 in Elden Ring"
   - "The user is on chapter 4 of the novel" → "The user is on chapter 11 of the novel"
   - "The user is watching season 2 of Succession" → "The user is watching season 3 of Succession"
   - "The user's daughter is in grade 3" → "The user's daughter is in grade 4"
   - "The user finished round 2 of interviews at Google" → "The user finished round 3 of interviews at Google"
   - "The user's character is level 12" → "The user's character is level 20"
   - "The user is in week 6 of the training plan" → "The user is in week 9 of the training plan"
   - "The user's team is in stage 2 of the project" → "The user's team is in stage 3 of the project"
   Assertions per row: older `status == "superseded"`, older `superseded_by == newer_id`,
   newer `status == "active"`, `result["flagged"] == 0`.

2. `test_d5_part_b_position_shapes_supersede` — same assertions for the three frozen Part B
   shapes (`ku_labels6.py`):
   - "The user is currently on page 200 of A Short History of Nearly Everything" → "The user is now on page 220 of A Short History of Nearly Everything"
   - "The user is currently on episode 10 of the Crash Course Science series" → "The user is currently on episode 50 of the Crash Course Science series"
   - "The user's goal is to reach level 100 in Apex Legends" → "The user's goal is to reach level 150 in Apex Legends"

3. `test_d5_identifier_keying_is_unchanged` — direct `comp._split_subject_slot` key assertions
   (keys must differ):
   - "Phase 1 was accepted after correction." vs "Phase 2 was accepted after correction."
   - "conv-26 baseline" vs "conv-30 baseline"
   - "Cairn at budget 600 scored 91.7% accuracy at 931 tokens" vs "Cairn at budget 1200 scored 91.7% accuracy at 1,613 tokens"
   - "b600 run" vs "b1200 run"
   - "Chapter 2: A League of Extraordinary Talent" vs "Chapter 3: Rising to the Challenge"
   Also assert the label list no longer holds the eleven progress nouns and still holds
   `phase`, `conv`, `budget`, `section`, `question`.

4. `test_d5_hyphen_joined_digits_after_an_unlisted_label_stay_in_the_key` (gap G1) —
   `comp._split_subject_slot("invoice-4471 was paid")[0] != comp._split_subject_slot("invoice-4472 was paid")[0]`,
   and both keys contain the number.

5. `test_d5_noun_modifier_is_the_only_reason_a_status_word_is_rejected` (gap G2) — older
   "The user is married", newer "The user is single-handedly running the bake sale": 0 superseded,
   0 flagged, older `active`; and `comp._relationship_status_slot("The user is single-handedly
   running the bake sale") is None`.

Docstrings must state the defect each test locks down, in the style of the existing tests.

## Rules

- Do not edit `docs/phase17-brief.md`, `reports/`, or anything under `eval/longmemeval/`.
- Do not weaken or rename existing tests.
- Python: the repo venv's `python` (bare `python3` is Xcode 3.9 and fails collection).
- Run: `cd <worktree> && env -i PATH=/usr/bin:/bin PYTHONPATH=src <repo>/.venv/bin/python -m pytest -q -p no:cacheprovider tests/`
  — must be 172 passed, 1 skipped (167 + your 5 new test functions, one parametrized ×10).
- Commit in the worktree with `git -c user.name=Polly -c user.email=polly@local commit`.
  Do **not** push; Polly verifies and pushes.
- Report `BLOCKED:` rather than guess if a dependency is missing.

## Report format

```
DONE: <one line>
FILES: <paths>
RAN: <exact commands>
OUTPUT: <real test output tail>
UNVERIFIED: <anything not proven>
```
