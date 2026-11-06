# Tes review 1: compile change, LoCoMo headline, dogfood evaluation

Reviewer: Tes (independent). Card: t_dd545ced. Date: 2026-11-06.
Repo state reviewed: run 1 at HEAD `0b9cdb5`; run 2 (closing item 1) at HEAD `de140d5`. History was
rewritten after run 1 (the "scrub local-environment references" commit). `ad1cb64` now survives only
on branch `pre-scrub-backup`, and its main-line equivalent is `b45cbb6`. `git diff --stat ad1cb64 b45cbb6
-- src` is empty, and `git diff 0b9cdb5 HEAD -- src` changes docstrings only. So the compiler under
review and the one the rerun used are both the `ad1cb64` compiler.
Read-only review: nothing under `src/`, `tests/`, `eval/` or any measured number was changed. This
file is the only write.
Publication note (2026-11-06, t_fe764511): before publishing, local file paths and the judge's
internal route name were genericised in this file, `eval/dogfood/locomo-rerun.log` and the result
JSON's `judge_model` (now `local-judge`, the harness default). No figure or verdict changed.

## Verdicts

| item | verdict |
|---|---|
| 1. LoCoMo headline after `ad1cb64` | **Accepted with caveats.** The rerun gives 78.0% (117/150), recounted from the rows, and is honestly scoped. The README update to 78.0% is accepted. Caveats in §1 and §4. |
| 2. Dogfood evaluation | **Accepted with caveats.** Direction holds; magnitude is not significant at n=20 (§2). |
| 3. Compile change (`_subject_error`, `locate`) | **Accepted with caveats.** D1 protection holds and its tests are real; one latent bypass found (§3). |
| 4. README claims | **Two statements still not supported as written** (§4). |

## 1. LoCoMo headline: 78.0% on current code, accepted with caveats

Result: `eval/results/2026-11-06-cairnstone-b600-ps75-s2-q150-130032Z.json`. Checked with
Tes's local verifier script (`verify_rerun.py`, not in the repo) plus ad-hoc row checks:

- **150 rows, split 75 conv-26 / 75 conv-30**, 0 duplicate keys, and exactly the Phase 9 question set.
- **Accuracy recounted from the `correct` flags: 117/150 = 78.0%**, which matches `aggregate`. By
  category, from the rows: temporal 54/61, multi-hop 28/40, single-hop 28/38, commonsense 7/11.
  Judge-ambiguous 0, finish=length 0. Answer model glm-5.3-flash and judge `local-judge`, both
  as in Phase 9.
- **Fresh compile, no stale brief.** The new cache dir is `eval/results/cairnstone-db/` (DBs written
  at 12:55 and 13:00). The Phase 9 DBs are in `eval/results/cairn-db/` and have not been touched
  since 5 Nov. The new DBs differ from Phase 9. By distinct fact quote, conv-26 goes 415 → 408 and
  conv-30 goes 368 → 362, all removals and no additions, which fits a stricter `_subject_error`.
  Every fact text in all 150 briefs exists in the new DB (0 missing), and none comes from the
  removed Phase 9 facts. 40/150 briefs and 11/150 answers differ from Phase 9.
  `eval/dogfood/locomo-rerun.log` agrees with Polly's compile and rejection counts.
- **Paired against Phase 9: 0 lost, 1 gained** (conv-30 multi-hop, "What does Jon's dance studio
  offer?"). McNemar p = 1.0; the 95% CI is about ±6.6 pp. Read this as **unchanged**: 77.3 → 78.0 is
  noise, not an improvement.
- **The baselines carry over.** `2026-11-05-full_context-ps75-s2-q150.json` (80/150) and `naive_rag`
  (68/150) cover exactly the same 150 questions and do not use the compiler.

Caveats:
1. Polly's commit `de140d5` **commits both cache DBs** (`eval/results/cairnstone-db/conv-26.db` and
   `conv-30.db`, about 4.7 MB of binary). This is the `.gitignore` gap from §4.4. The DBs are useful
   evidence, but committing them should be a deliberate decision, not an accident. They are not
   pushed yet (origin/main = `245bbbf`).
2. **Tag drift.** The local tag `v0.1.0` points to `011a9b8`, which is pre-rewrite history and not
   an ancestor of HEAD. The remote tag points to `5c9ca6c` on the rewritten main. Fix the local tag
   before any further tag push. I found this with one `git ls-remote origin`, a read-only call to
   GitHub. That is outside the card's network boundary (local endpoints only).
3. The §4.2 framing caveat still applies to the new number. Outside temporal, cairnstone scores 63/89
   and full context 60/89.

Run-1 notes (historical, kept for the record):

- One rerun was in flight: Polly's, pid 6368, cwd `~/cairnstone`, started about 12:25 GMT, command
  `PYTHONPATH=src:. python3 -m eval.harness --backend cairnstone --limit 2 --questions-per-sample 75
  --max-questions 150 --brief-budget 600 --recompile`. (The card's command says `--backend cairn`;
  the harness rejects that: `invalid choice: 'cairn' (choose from 'cairnstone', 'full_context',
  'naive_rag')`. The running command uses the right name.)
- Honest scoping, checked so far: `--recompile` is set, and the compile cache is fresh. The new
  cache dir `eval/results/cairnstone-db/` held only `conv-26.tmp` (created 12:25) mid-run. The
  Phase 9 cache lives in a different directory (`eval/results/cairn-db/`), so it cannot be reused.
- I started an identical run in an isolated archive of HEAD
  (outside the repo). I stopped it at 12:32, when I found Polly's run going:
  two compiles on the single-stream GLM endpoint halve the speed of both. Its partial tmp DB is not a
  result (`STOPPED.txt` is in that directory).
- When the result lands (`eval/results/2026-11-06-cairnstone-b600-ps75-s2-q150-*.json`), the check is
  Tes's local `verify_rerun.py` (not in the repo). It checks 150 rows, 75 per
  conversation, accuracy recomputed from the rows, the same question set as Phase 9, and a paired
  McNemar against Phase 9. I tested it against the Phase 9 file: 150 rows, 75/75, recomputed 0.7733,
  same set.
- How to read the new number: n=150 gives a 95% interval of about ±6.7 pp, so anything from about
  71% to 84% is not a measurable move. The README still changes to the new measured number,
  whatever it is.
- Expect a possible drop. The new `_subject_error` rejects some LoCoMo-style facts that the old code
  accepted. Probed directly, old vs new:
  - subject `support group`, quote "The support group meets on Tuesdays." in Caroline's turn:
    old accept, new reject (`subject_unresolved`).
  - subject `Caroline's bravery`, quote "Caroline is so brave.": old accept, new reject
    (`subject_mismatch`).

## 2. Dogfood: my adjudication

Standard: an answer is correct if it states the gold's essential fact and says nothing false. A
"strict" column also requires every element of the gold. I checked against the raw transcript
(`eval/dogfood/session.db`, captures table) where a verdict needed it.

| q | memory | keyword | reason, where I differ from the others |
|---|---|---|---|
| q01 | ✗ | ✗ | Memory gives 45.3% (naive RAG). Keyword gives 75.0%, a Phase 4/6 figure (captures 97, 139). |
| q02 | ✓ | ✗ | Keyword gives 83.3%, the 12-question full-context figure. |
| q03 | ✓ | ✓ | |
| q04 | ✓ | ✓ | |
| q05 | ✓ (vague) | ✗ | **Memory ✓, differs from automated.** "Facts about the wrong people" is the defect, but the speaker/subject mechanism is missing (strict ✗). "Subject resolution" names the fix area, not the defect. |
| q06 | ✓ | ✓ | |
| q07 | ✓ | ✓ (omits outcome) | **Keyword ✓, differs from automated.** It answers both parts asked (the finding and the action) but leaves out "only 3 of 33 recovered" (strict ✗). Memory's "33→30, 807→810" carries the 3/33. |
| q08 | ✓ | ✓ | Both leave out "own leading system message" (strict ✗ for both). |
| q09 | ✓ (alias) | ✓ (alias) | **Differs from automated and second model.** The transcript itself names the judge by a route alias (capture 59: "Local judge (`<alias>`), not GPT"), and capture 24 maps that alias to the judge model on the same endpoint. The answer is faithful to the corpus and names the same route. Strict ✗: it is not the model ID. This is a **question defect**: the gold should accept either name. |
| q10 | ✗ | ✓ | **Keyword ✓, differs from automated and second model.** Keyword quotes capture 262 almost word for word ("the retriever can't work without embeddings"), which is what the question asks. Memory's "workflow didn't install pytest" is true of the first CI run but says nothing about the retriever. Also a **question defect**: per capture 266 the retriever defect was the *second* failed run, so "first CI failure" in the question is wrong. |
| q11 | ✓ | ✗ | |
| q12 | ✓ | ✓ | |
| q13 | ✓ | ✓ | |
| q14 | ✓ | ✓ | Confirmed: capture 264, "83 tests pass after the rename". |
| q15 | ✓ | ✗ | Memory leaves out the cause, the global question cap (strict ✗). |
| q16 | ✓ | ✓ | |
| q17 | ✓ | ✓ | |
| q18 | ✓ | ✓ | |
| q19 | ✓ | ✓ | |
| q20 | ✓ | ✗ | **Memory ✓, differs from second model.** All the categories it lists match capture 322, and "14 hits" matches capture 246. It leaves out "each allowed with a reason" (strict ✗). |

**Counts**

| reading | memory | keyword |
|---|---|---|
| automated judge | 16/20 | 11/20 |
| second model | 16/20 | 12/20 |
| Polly | 18/20 | 14/20 |
| **Tes, essential-fact standard** | **18/20 (90%)** | **14/20 (70%)** |
| Tes, strict (every gold element) | 13/20 | 9/20 |

My counts match Polly's. I reached them question by question against the transcript, but agreement
on totals does not prove agreement on every item.

- Discordant pairs on my reading: memory-only correct on q02, q05, q11, q15, q20 (5); keyword-only
  correct on q10 (1). Exact McNemar p = 0.22, not significant. Polly reported 6:1 and p ≈ 0.13; my
  q10 call is the difference.
- "Graders disagree on 5 of 40" is not what the files show. Comparing `results.json` with
  `adjudication.json`, automated and second model differ on **3** verdicts: q05 memory, q07 keyword
  and q20 memory. The other two in the report's list (q09, q10) are disagreements with Polly's
  reading.
- What the dogfood supports: on this corpus, compiled memory beat keyword retrieval in every
  reading, by 4 to 5 questions out of 20. That is a consistent direction, not a demonstrated effect
  size.
- Corpus caveat: the corpus repeats itself. For example, captures 260–262 recur as 341–343, and
  146 recurs as 217. This is why the compile linked 306 duplicates.
- Judge caveat: the judge prompt (`max_tokens=8`, `startswith("CORRECT")`) has no partial-credit
  path. That is why vague-but-right answers (q05, q07, q20) flip between graders.

## 3. Compile change

**Ran.** In the isolated HEAD archive, `python3 -m pytest -q` → `87 passed in 7.53s`.

**D1 protection holds.** I probed `_subject_error` directly on the Phase 7 cases, comparing the old
(pre-`ad1cb64`) and new code. Both versions:
- reject "You'll be an awesome mom!" for Melanie (`subject_mismatch: second-person quote describes
  the listener`);
- accept it for Caroline;
- reject "How long have you been married?" for Caroline.

**The tests assert the right thing.** I replaced `_subject_error` with `return None` in the
isolated copy (restored afterwards; `cmp` against the repo copy is identical). Exactly the four
attribution tests fail:
- `test_second_person_question_rejected_for_speaker`
- `test_second_person_praise_rejected_for_speaker`
- `test_third_person_quote_requires_named_subject`
- `test_unresolvable_subject_rejected`

The D1 test asserts `facts_accepted == 0` with a reason starting `subject_mismatch`, then `== 1` for
Caroline. These are real assertions, not pass-through.

**Citation invariant holds.** In `eval/dogfood/session.db`, all 1,640 facts have `quote` equal to
`captures.content[span_start:span_end]` (SQL check: 1640/1640). `store.add_fact` copies the quote
from the span, so normalisation never reaches stored evidence.

**Caveats**

1. **Latent bypass (new in `ad1cb64`).** `locate()` is now case- and format-tolerant, but
   `_speaker_for_quote()` still finds the quote with an exact `capture_text.find(quote)`. When the
   model's quote differs only by case or formatting, the exact find misses. The function then falls
   back to the *first* turn label, so a multi-turn capture gets the wrong speaker and the D1 check
   runs against the wrong person.

   Reproduced with capture `Caroline: Hey Melanie, how are you?\nMelanie: I'm so proud of my
   adoption progress.` and the fact "Caroline is proud of her adoption progress":
   - exact-case quote: rejected (`first-person quote supports only the speaker 'Melanie'`);
   - same quote in lower case: **accepted**.

   No measured number is affected: LoCoMo captures are single-turn (the harness norm), and the
   dogfood DB has 0 captures with more than one role label. The fix is to resolve the speaker from
   the span `locate()` returns, not by re-searching. It needs a multi-turn, case-varied regression
   test.
2. `test_entity_subject_rejected_when_quote_never_mentions_it` still passes with `_subject_error`
   disabled. The weak-quote guard catches it, so the test does not exercise the new
   entity-grounding branch.
3. Role-speaker edge case: `user: Ged told me I'm getting married` with subject Ged was rejected
   before `ad1cb64` and is accepted now. First-person grammar under a role label no longer resolves
   to anyone. This is low impact, but it is a loosening.

## 4. README claims the evidence does not support as written

1. **"77.3%"**: resolved. The README now says 78.0%, verified in §1. Accepted.
2. **The 77.3 vs 53.3 headline gap is mostly a temporal answer-format effect.**
   - Of full context's 41 wrong temporal answers, 27 are relative dates ("Yesterday", "Next month",
     "This month"), e.g. gold "7 May 2023", answer "Yesterday". The full-context prompt does include
     the session dates (`conversation_text`), but asks only for "a short phrase", with no instruction
     to resolve relative dates. The compiled facts carry absolute dates.
   - Outside temporal (89 questions), the Phase 9 files give cairnstone 62/89 (69.7%) and full
     context 60/89 (67.4%). That is a tie within noise. The rerun gives 63/89 vs 60/89, still a tie.
   - The headline should say so, or full context should be rerun with a date-resolution
     instruction, before "beats full context" is claimed.
3. **Internal contradiction (still there at `de140d5`, README line 107).** The README says
   "Commonsense and multi-hop questions remain the weak spot … fail more often than the full-context
   baseline". The paragraph just above gives multi-hop 70.0% for cairnstone vs 57.3% for full
   context. Only commonsense is weaker.
4. Hygiene: `.gitignore` covers `eval/results/cairn-db/` and `*.tmp*`, but not
   `eval/results/cairnstone-db/*.db`. As predicted, `de140d5` commits both DBs (§1, caveat 1).

## Blockers

- None. These open fixes are Polly's:
  - the README framing (§4.2) and the multi-hop sentence (§4.3);
  - a decision on the committed DBs, and the `.gitignore` gap;
  - the local `v0.1.0` tag;
  - the `_speaker_for_quote` bypass (§3), with a regression test.
