# Tes review 5: phase 17 Part A (F1-F4) at `d9a4da7`

**Verdict: REJECT Part A as the base for Part B, on two defects (D1, D2).** F1 and F2 are correct and
accepted as they stand. F3 and F4 each fixed the case they were written for, but each over-corrected
in a way that the tests and the collateral probe cannot see, and both hit exactly the facts that
Part B (the knowledge-update experiment) measures. Part B must not start until D1 and D2 are fixed and
re-reviewed. The fixes are small. Neither needs a redesign.

Everything below was run by me in a detached worktree at `d9a4da7`, with `PYTHONPATH=src` so the
editable install could not import the main checkout. The comparison baseline was a second worktree
at `fe71ff1`. Scripts and raw outputs are attached to the review card (`t_c5609d38`).

## Baseline facts

- `main` = `d9a4da7`. Working tree clean. CI run 42869601965: `completed / success`,
  `headSha d9a4da74c4216604ba48751e4eaede9828c1f52c`.
- Main checkout: **143 passed**. My worktree: 142 passed, 1 skipped. The skip is
  `test_quote_integrity.py:113`, which needs the gitignored local redaction-rules file. Same tests
  otherwise.
- Corpus for the probe: the same 27 databases (dogfood `session.db`, conv-26 and conv-30 in both
  result dirs, 22 LongMemEval DBs). I copied them out, verified SHA-256 of all 27 originals before and
  after (0 changed), and the probe itself works on SQLite backup copies.

## 1. F1 (page scope): ACCEPTED

- Code: `_supersede_contradictions` groups canonical rows by `page_id` and builds a fresh `claims`
  dict inside the per-page loop (`compile.py` 713-733). Nothing carries across pages except
  `superseded_ids`, which only prevents double-retiring a row.
- Tests: `test_f1_fact_on_page_a_cannot_supersede_or_flag_a_fact_on_page_b` asserts both facts active
  and zero flags. `test_f1_same_page_genuine_contradiction_still_supersedes` asserts `superseded` and
  `superseded_by`.
- Mutant: one brain-wide `claims` dict shared across pages. The page-A/page-B test fails
  (`1 failed, 8 passed`). The guard can fail.
- Real data: at `d9a4da7`, **0 of 14 flags and 0 supersessions pair facts on different pages**
  (I joined every new flag and supersession to the page paths). At `fe71ff1` it was 20 of 43
  (2 of 3 supersessions, 18 of 40 flags). That matches the "20 of 43" figure in P6 exactly.
- P6 wording: it says the scan compares within one page, that cross-page contradictions are neither
  superseded nor flagged, and cites the Fitbit tenure pair in `08e075c7.db`. Measured: that pair stays
  active, with no flag, at `d9a4da7`. The wording matches the code.
  One correction is needed (D4): the illustrative "`projects/alpha` first CI run" example comes from
  the review-4 probe, not from this corpus. See item 5.

## 2. F2 (the n6 guard can fail): ACCEPTED

- `test_n6_phrasing_variant_relationship_contradicts` now asserts
  `("cat:relationship_status:caroline", "married") in _fact_slots("Caroline got married in May 2023")`.
- `test_n6_stale_single_is_superseded_by_the_married_fact` asserts `status == "superseded"` and
  `superseded_by == f2` (the married fact).
- I re-ran the mutant myself: `_fact_slots` returns `[]` when the text contains "got married".
  Result: **`2 failed in 0.07s`**, and the two failures are those two tests. Polly's
  "2 failed in 0.08s" is verified. Unmutated, both pass.

## 3. F3 (identifiers and "as of"): the stated cases pass, but the change has a serious over-correction (D1)

What works:
- "phase 1/phase 2", "budget 600/1200" and `conv-26/conv-30` key apart and stay active. The tests
  fail under the mutants: identifier digits off makes 2 fail, as-of strip off makes 1 fail.
- A bare trailing "as of 2023-05-22" is dropped. "Caroline completed a triathlon" and the same
  sentence "… as of 2023-05-22" key as one claim. A leading "As of 2026-11-05 the build…" is
  left alone, as the docstring says.
- `test_f3_genuine_value_change_still_supersedes` passes. On real data F3 removes only true false
  positives: with F3b ablated, the HEAD pass would add 7 flags, all identifier pairs
  (b600/b1200/b4000, budget 600/1200/4000). With F3a ablated it adds 1 supersession
  ("first CI run failed" vs the same sentence stamped "as of 2026-11-06") and 2 flags.

**D1 (blocking): `_is_identifier_digit` treats any non-boilerplate word before a number as an
identifier label, verbs included.** Only prepositions and boilerplate are value contexts. So in
"owns **15**", "has read **12**", "ran **5** km", "watched **12** episodes", "saved **300**",
"completed **70**%", "over **30**", "at least **30**", "scored **85**", "spent **8** hours", "got
**20** likes", the count is frozen into the KEY. A later, different count is then a different claim,
and the old one is never superseded or flagged.

The only genuine-change test (Fitbit) puts its number after "for", a value context. So it passes,
and the regression is invisible to the suite.

Evidence: I put the same-page pair (older, then newer capture) through `consolidate()` under both trees.

| older -> newer | `fe71ff1` | `d9a4da7` |
|---|---|---|
| owns 15 -> 17 Funko Pops | superseded | **active** |
| has 3 -> 4 cats | superseded | superseded |
| has read 12 -> 15 books this year | superseded | **active** |
| ran 5 -> 10 km on Saturday | superseded | **active** |
| personal best 5K time is 25 -> 23 minutes | superseded | superseded |
| recorded over 30 -> 45 bird species | superseded | **active** |
| guitar at least 30 -> 45 minutes every day | superseded | **active** |
| watched 12 -> 20 episodes of The Crown | superseded | **active** |
| rent is 1200 -> 1400 per month | superseded | superseded |
| completed 70% -> 90% of the storyline | superseded | **active** |
| Instagram has 500 -> 650 followers | superseded | superseded |
| saved 300 -> 450 dollars for the trip | superseded | **active** |

**8 of 12 genuine updates no longer resolve.** Some were phrased the way the LongMemEval
knowledge-update questions read: "how many bikes do I currently own", "how many Korean restaurants
have I tried", "how many hours on the sculpture", "how many pages have I read", "how many short
stories", "how many sessions did I attend", "how many engineers do I lead". In 7 of 8 such phrasings
the old and new facts get different keys (`user own 3 bike` vs `user own 4 bike`).

Corpus scale: F3b changes the key of 1,403 of the 10,300 unique active fact texts. In 264 of those,
the "label" is a verb or a quantifier (scored, over, achieved, got, spent, measured, cost, takes,
at least, sold, earned…). This is exactly the knowledge-update population Part B is meant to test.
Running Part B on this code would measure the consolidation pass with its main mechanism switched
off for counts.

Why the collateral probe cannot see it: the probe only counts what changed. These DBs happen to hold
no same-page count-update pairs of this shape, so turning a supersession into nothing shows up as
nothing.

Fix direction (Polly's call, kept small): invert the rule. A digit is an identifier only when it is
attached to a word (`b600`, `v2`), or when the preceding word is on a short identifier-label list
(phase, conv, sample, budget, n, v, version, tier, step, port, pid, issue…) or is a hyphen-joined
label (`conv-26`). Every other preceding word leaves the number as a value. Add the failing rows
above as tests, at least "owns 15 -> 17" and "has read 12 -> 15", and run them as mutants.

## 4. F4 (state immunity and the subject cut): classification correct, but the cut merges slots it should not (D2)

What works:
- married, wed, eloped, separated, engaged and relocated phrasings classify as described. "married
  `<Name>`" is anchored as an event. met, left and joined are gone from immunity. The tests fail
  under their mutants: no `_MARRIED_VERB_RE` makes 2 fail; no forward cut makes
  `test_f4_false_event_hits_do_not_make_states_permanent` fail.
- Planning verbs are excluded. Adding "plans" to the verb set makes
  `test_plan_fact_does_not_contradict_status_fact` fail, so that test really guards the exclusion,
  and it passes at HEAD.
- The defect F4 exposed is real and fixed. "Caroline met her husband through work and is married" now
  reaches `cat:relationship_status:caroline`.

**D2 (blocking): the forward cut turns incidental category words into live slot claims about the
subject.** `_fact_slots` still matches "single", "dating", "engaged" and "married" anywhere in the
sentence. Before `d9a4da7`, an off-topic match landed on a long nonsense key, such as
`cat:relationship_status:the user is working on new comedy material about online`, so it was inert.
Now the subject is cut at the first action verb, so the same match lands on
`cat:relationship_status:the user` and competes with the real status:

| older fact (same page) <- newer fact | `fe71ff1` | `d9a4da7` |
|---|---|---|
| "The user is married" <- "The user is working on new comedy material about online dating" | active | **superseded** |
| "The user is single" <- "The user bought a gift for her friend who is getting married" | active | **superseded** |
| "The user is single" <- "The user works with a colleague who is divorced" | active | **superseded** |
| "Caroline is married" <- "Caroline is planning to become a single parent" | active | **superseded** |
| "Caroline is married" <- "Caroline is thinking about becoming a single parent" | active | **superseded** |
| "Caroline is married" <- "Caroline is becoming a single parent" | active | **superseded** |
| "Caroline is married" <- "Caroline plans to become a single parent" | active | active (the plan exclusion works for "plans to" only) |
| "Caroline is single" <- "Caroline is married" (the real case) | superseded | superseded |

Corpus scale: the cut changed the categorical slot of 49 unique fact texts. Most went from an inert
long key to a bare live subject key: `the user` ×8, `user` ×3, `chris` ×2, `rachel` ×2, `caroline`, and
others. Real examples: "The user is working on an online dating joke" becomes
`relationship_status:the user = dating`. "User has been using a single-action airbrush" becomes
`= single`. "User is planning a themed dinner party … keep guests engaged" becomes `= engaged`.
These are the user-centred LongMemEval pages Part B runs on.

The suite missed it because no test puts an off-topic category word on the same page as a real status
with a later timestamp.

Fix direction: after the cut, require the category word to be the predicate of the main clause. That
means it directly follows the subject plus a copula/state verb, possibly with a short adverb ("is
single", "got married", "is now dating X", "is getting married"). Reject a match that sits inside a
relative clause ("who is …"), after a preposition ("about online dating"), or as a noun modifier
("single parent", "single-action", "single family", "engaged guests"). "Is getting married" is
borderline. I would treat it as a plan, like "plans to". Add the D2 rows as tests.

## 5. Collateral probe: REPRODUCED

I re-ran `eval/probe_phase17.py` myself under both trees: 27 databases, backup copies, two passes.

| tree | superseded | flagged | duplicates_linked (counter) | rows whose `duplicate_of` changed |
|---|---|---|---|---|
| `fe71ff1` | 3 | 40 | 35 | 57 |
| `d9a4da7` | **0** | **14** | **39** | 61 |

- Polly's 0/14/39 and her 3/40/35 baseline reproduce exactly.
- The 57 in the brief (and in review 4) is a different measurement: rows whose `duplicate_of` value
  changed. My row diff gives 57 at `fe71ff1`, exactly. Polly's 35/39 is the `duplicates_linked`
  counter that `consolidate()` returns. Both are right; they count different things. Use one name per
  number from now on.
- **Second pass is a no-op on all 27 DBs** (pass 2 = 0/0/0 everywhere, under both trees).
- **The three lost supersessions are NOT all cross-page.** Two are cross-page, both
  `misc/user -> people/user`: the Fitbit tenure pair (`08e075c7`) and the Dear Evan Hansen
  "since December 2022 -> since 2022-12-01" pair (`gpt4_76048e76`). The third, "The first CI run for
  Cairnstone failed" -> "… as of 2026-11-06" in the dogfood DB, is **same-page** (`projects/cairnstone`,
  page 150). F3a removed it, not F1. That is correct: it is the same claim restamped, not an update.
- **D4 (docs, minor):** P6 says the brain-wide scan's wrong pairs included "`projects/alpha` first
  CI run failed superseded by a `projects/beta` fact". In this corpus that sentence pair is same-page,
  and F3a resolves it. The alpha/beta case is from the review-4 probe. Reword the P6 example to one
  that is cross-page in this corpus (the Dear Evan Hansen pair works), and say the third lost
  supersession is an F3a effect.
- Remaining 14 flags at HEAD: all same-page. Of these, 1 is a correct ambiguity flag (Caroline
  single vs married, equal capture date), 1 is the documented residual (item 6), 4 are the known
  occupation-noun flags (mom/parent and dancer/teacher, ×2 result dirs), 2 are motion-date pairs, and
  6 are LongMemEval location/occupation or re-stamp flags (7527f7e2 ×3, 85fa3a3f, c8090214,
  gpt4_76048e76). Only the residual is a new kind compared with `fe71ff1`.

## 6. Residual false positive (Caroline married vs "becoming a single parent"): MUST BE FIXED BEFORE PART B

The report describes this as a flag. In the dogfood DB it is only a flag because both captures carry
the same date. With any later timestamp on "becoming a single parent", it **supersedes "Caroline is
married"** (row 6 of the D2 table). LongMemEval captures carry distinct session dates, so in Part B
this class would silently retire true facts, not just raise review flags. It has the same root cause
as D2, and the D2 fix (category word must be the main-clause predicate, "single parent" is a noun
modifier) closes it. Fix them together, with this exact pair as a test, with later timestamps.

## Numbered defects

- **D1 (blocking).** F3b freezes counts after verbs and quantifiers into the slot key. 8 of 12
  genuine count updates stop superseding. Directly undermines Part B.
- **D2 (blocking).** The F4 forward cut moves incidental category words ("online dating", "single
  parent", "single-action", "engaged guests", "friend who is getting married", "colleague who is
  divorced") onto the subject's live relationship slot. Off-topic later facts now supersede a true
  status.
- **D3 (blocking, same root as D2).** The documented Caroline residual is a supersession, not only a
  flag, whenever the timestamps differ.
- **D4 (minor, docs).** The P6 example of a cross-page wrong pair is not cross-page in this corpus. One
  of the three lost supersessions is same-page (F3a), not cross-page. Name the two duplicate
  measurements distinctly.

## What I did not verify

- No question-level measurement (LoCoMo / LongMemEval). That is Part B and card `t_788a7752`.
- The D1/D2 impact on Part B is inferred from synthetic same-page pairs and from key changes over the
  corpus. I did not run Part B arms to measure it.
- `retrieve.py` changes in this range belong to `ebee5f6` (dated citations). They are outside F1-F4
  and I did not review them.
- I did not review the Part B harness files added in this range (`eval/longmemeval/ku_paired.py`,
  `p17_*`), or the rev-4 brief's Part B design.
- I did not re-check the quote-integrity test that skips in a fresh worktree. It passes in the main
  checkout.

## Re-review asks

Fix D1-D3 with tests that fail under a mutant. Re-run `probe_phase17.py` and report the per-DB
deltas from 0/14/39. Expect a few flags or supersessions back from D1, and that is the point. Then
send the commit back to Tes. If D1-D3 are clean, I expect to accept quickly, and Part B can start
after that.
