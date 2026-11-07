# Tes review 4 — independent verification of phase 16 (N7–N11) at `fe71ff1`

Reviewer: Tes. Card `t_e401c8e3`. Date: 2026-11-07. Base `d73b6ae`, head `fe71ff1` (= `origin/main`).
Read-only on `src/`, `tests/`, `docs/`; this file is the only repo write and is left untracked.
Probes, mutants and outputs live in Tes's scratch area (`cairn-review4/`), not in the repo.

## Verdict

**Phase 16 can be accepted with two follow-ups.** N8, N9 and N10 are fixed. N7 and N11 are fixed for
the defects as reported, but each has a gap (below). The suite counts in Polly's report reproduce exactly.

Two things the report does not say, both of which should go to Polly before README claims are rebuilt
on this code:

1. **F1: contradiction scope widened from one page to the whole brain, without a mention.** P6 still
   says "two active facts *on one page*". The rewritten `_supersede_contradictions` builds one
   `claims` dict across every page, so a fact on one page can now supersede or flag a fact on another.
2. **F2: the rewritten `test_phase15` n6 test no longer protects N6, and the report says it does.**
   A mutant that gives "got married …" facts no slots at all passes the whole suite.

## Test counts (reproduced)

| Tree | Command | Result |
|---|---|---|
| `fe71ff1` (main checkout, HEAD = origin/main) | `.venv/bin/python -m pytest -q` | **133 passed** |
| own worktree at `d73b6ae` + gitignored `eval/dogfood/session.db` and `redaction_rules.local.json` | same | **115 passed** |
| same worktree + `tests/test_phase16.py` copied in | `pytest -rA tests/test_phase16.py` | **15 failed, 3 passed** |

I confirmed the worktree imports its own `src` (a pytest plugin printed
`cs-d73/tests/../src/cairnstone/compile.py`). The failing and passing tests match the report: the three
passers are `test_n8_event_vs_state_pair_is_not_a_brief_contradiction`,
`test_n9_parseable_captured_at_is_silent` and `test_n11_event_not_flagged_against_a_later_state`.

**Are the three passers real guards?** I checked by breaking the code each one guards:

| Mutant at `fe71ff1` | Test that catches it |
|---|---|
| drop the event/state skip in `retrieve._contradiction_notes` | `test_n8_event_vs_state_pair_is_not_a_brief_contradiction` fails |
| `cmd_ingest` always prints a warning | `test_n9_parseable_captured_at_is_silent` fails |
| drop the event/state skip in `_resolve_slot` | `test_n11_spouse_split…` and `test_phase15 n6` fail. `test_n11_event_not_flagged…` still passes because at `d73b6ae` the pair superseded rather than flagged |

So two of the three are real guards. The N11 one only guards against a flag, not against supersession;
the spouse test covers supersession. That is acceptable. (In my copied trees
`test_quote_integrity::test_export_structure` fails because the dogfood path is relative. That is an
artifact of the copy and fails on the unmutated copy too.)

## Per-defect verdicts

Probe: `probe.py` run under each `src` (`probe-fe71ff1.out`, `probe-d73b6ae.out`).

### N7 — slot keys carry no extractor phrasing: **fixed (literal strings); partially on live extraction**

`_fact_slots` on the exact `tes-review-3.md` strings at `fe71ff1`:

```
'Caroline has been working as a nurse for 4 years as of 2023-05-08.' -> ('caroline nurse year', ('4','2023','05','08')) + cat:occupation:caroline
'Caroline has been a nurse for 5 years.'                             -> ('caroline nurse year', ('5',))
'Caroline has 1 child.' / '2 children.' / '3 children.'              -> ('caroline child', ('1',)/('2',)/('3',))
"Caroline's spouse is Tomas."                                        -> ('caroline spouse toma', None) + cat:relationship_status:caroline = married
'Caroline is married.'                                               -> ('caroline married', None)   (no more 'mar'+'ried')
'Caroline went to Mar del Plata in March 2023.'                      -> value ('mar','march','2023')  (month matching still reads place-name "Mar"; harmless here)
```

When I replayed the 15-fact Spark scenario from review 3, the 4-year tenure is superseded by the
5-year one (f4 → f12). At `d73b6ae` both stayed active.

**Live extraction** (`spark.py`, the review-3 script plus a third night, real calls on the Spark pair
`:8889` DeepSeek extraction route, run 19:23Z, about 20 s in total):

- The review-3 phrasings came back verbatim and keyed correctly: f4 "4 years" was superseded by f12
  "5 years", and the review-3 N7 defect does not reproduce.
- Real extractor variants still miss:
  - "Caroline has one child, Ana, who is two years old." keys as `caroline one child ana who two year old`.
  - "Caroline has two children, Ana and Leo." keys as `caroline two child ana and leo`.
  - "Caroline has been nursing for six years as of August 2023." keys as `caroline nursing six year`.

  Spelled-out numbers stay in the key, and so do appositive names and `nursing` versus `nurse`. The
  stale "one child" stays active beside "two children". This is a coverage limit, not a regression.
  At `d73b6ae` these would not have matched either.

### N8 — Earlier/Unresolved in the brief: **fixed**

- Berlin (May) versus Lisbon (June) gives `Earlier: Caroline lives in Berlin (contradicts … Lisbon)`.
  It gives the same line when Lisbon is inserted first, so the note follows the stamp and not the
  insertion order. At `d73b6ae` the Spark replay produced three inverted
  `Earlier: …Lisbon… (contradicts …Berlin…)` lines.
- Equal stamps give `Unresolved: … capture times not comparable`.
- A resolved pair (single May / married June) shows an Earlier note before consolidation and none
  after, because the superseded side is skipped.
- Event versus state ("moved to Lisbon" / "lives in Berlin") gives no note.
- Minor: a *dated* versus an *undated* fact produces `Earlier:`, not `Unresolved:`. This happens
  because `_capture_stamps` compares raw `captured_at` strings and ignores `captured_at_explicit`.
  The report says "missing or unparseable" stamps give Unresolved. An undated capture has a stamp
  that parses (it is the ingest time), so the code does what its words say. Even so, the brief
  disagrees with consolidation, which treats the dated fact as current. This is low severity.

### N9 — missing/unparseable `--captured-at`: **fixed**

```
ingest (no --captured-at)          rc=0  stderr: warning: no --captured-at given; this capture is stamped with ingest time and will not outrank dated history
ingest --captured-at='next tuesday' rc=0  stderr: warning: --captured-at 'next tuesday' is not a parseable timestamp; it is stored verbatim and treated as undated
ingest --captured-at=2023-05-01     rc=0  stderr: (empty)
captures: explicit = 0, 0, 1
```

**Migration on the real dogfood DB** (a backup copy): before the migration the column was absent.
After `init_db`, all 366 captures have `captured_at_explicit = 1` and `_capture_clocks` reports all
366 known. The concern from review 2 is closed, and this also covers a "did not verify" item from
Polly's report.

### N10 — P11 halt is a rollback: **fixed**

With 5 facts and `max_mutation_rate=0.1`:

- Pass 1 raised `PolicyHalt` ("…the pass was rolled back…").
- Afterwards the fact rows, the `duplicate_of` links and the change-event count were identical to the
  start, and `in_transaction=False`.
- Pass 2 halted again with the same message.
- Without the limit, the pass applied 1 duplicate, 1 superseded and 1 flag.

P11 in `docs/compile-policies.md` states the rollback semantics.

### N11 — spouse slot + event history: **fixed for the reported phrasings; bounded list has gaps both ways**

On the Spark replay, both the live run and the literal replay give the same result:

- "Caroline is married" (f9) and "Caroline's spouse is Tomas" (f11) are superseded by the July
  "Caroline is single" (f14).
- "Caroline got married on 2023-06-10" (f10) stays active.
- "split up with Tomas" stays active.

This is the review-3 ask. At `d73b6ae` the opposite happened: f10 was superseded and f11 stayed active.

`_EVENT_MARKER_RE` misses and false hits. In each case the event comes first and the state later:

| Text | `_is_event_fact` | Outcome at `fe71ff1` |
|---|---|---|
| "Caroline married Tomas in June 2023" | False | **superseded** by later "single" (N11 not applied: no `got married`/`married on`) |
| "Caroline got engaged to Tomas" | False | superseded (debatable) |
| "Caroline eloped / wed Tomas …", "relocated to Lisbon", "separated from Tomas" | False | active, but only because they reach no categorical slot |
| "Caroline met her husband through work and is married" | **True** | a *state* that a later state can now never retire |
| "…left-handed", "…the club she joined" | True | same: false event, so immune to supersession |

"X married Y" is a common extractor phrasing, so that miss matters for N11. The false hits (`met`,
`left`, `joined`) matter more over time: any state sentence that contains one of those words becomes
permanent. **Recommendation:** add `married <Name>`, `wed`, `eloped`, `separated`, `engaged`,
`relocated`. Anchor `met`, `left` and `joined` to verb position after the subject, or drop them from
the state-immunity rule.

## Collateral damage (not covered by the phase-16 tests)

I ran the consolidation pass (2 passes, on SQLite backup copies) under both trees over 27 real
databases with 10.5k active facts: `eval/dogfood/session.db`, the conv-26 and conv-30 DBs, and 22
LongMemEval result DBs.

| | superseded | flagged | duplicate links |
|---|---|---|---|
| `d73b6ae` | 0 | 9 | 33 |
| `fe71ff1` | 3 | 40 | 57 |

**`_resolve_slot` does not mass-supersede.** On real data it made 3 new supersessions, all of them
correct or harmless:

- Fitbit "6 months as of June" → "9 months as of Sept".
- "since December 2022" → "since 2022-12-01".
- "first CI run failed" → "… as of 2026-11-06".

P11 would catch a runaway pass in any case, and the pass now rolls back cleanly.

**Singularisation does not cause false merges on real data.** Over 13,225 active facts in 31 DBs,
singularisation created exactly 4 key merges, all of them the same claim reworded
(`page/pages`, `work/works`, `name/names`, `product/products`). Tomas and Toma were not merged in the
probe either, because their values differed.

**F1: cross-page scope (undisclosed).** 20 of the 43 new supersessions and flags pair facts on
*different pages*. At `d73b6ae` the scan reset `seen` for each page. Now one `claims` dict spans the
brain. Some of the effect is good: the LongMemEval "user" facts are split between `misc/user` and
`people/user`, and the correct Fitbit supersession was a cross-page pair. Some is wrong:

- The probe superseded "The first CI run failed on 2026-11-05" (`projects/alpha`) with the
  `projects/beta` fact.
- Real flags paired `projects/phase-1` "Phase 1 was accepted after correction." with
  `projects/phase-2` "Phase 2 was accepted…".
- `projects/conv-26` "419 captures and 528 facts" was paired with `projects/conv-30`.

This contradicts P6 as written and `docs/phase16-brief.md` ("on the same page"), and no test covers
it. **Polly should decide** whether to restore page scope or keep brain scope keyed on the
subject/page entity, then document the choice in P6 and add a test.

**F3: identifier numbers are now treated as slot values.** Canonicalisation strips the punctuation
that used to keep these keys apart by accident. "Phase 1/Phase 2", "budget 600/1200/4000",
"conv-26/conv-30" and "motion in June 2004/December 2004" now share a slot, and the number becomes
the value. With different stamps the older one is **superseded** (probe F: phase 1 → phase 2,
budget 600 → 1200, triathlon → "triathlon as of 2023-05-22"). At `d73b6ae` these stayed active. On
the real DBs they only flagged, because the pairs shared a capture stamp:

- 6 budget flags and 2 Mammoliti flags.
- About 12 paraphrase flags where only an "as of <date>" suffix differs (bronchitis, MBA, swim laps,
  Jerry's Artarama and others).

I judge roughly 25 of the 40 new flags false. Flags are advisory and do not change status, but each
false one is noise for review. Also, a same-day re-ingest of any of those pairs would retire a true
fact. **Recommendation:** do not treat a bare "as of <date>" suffix as a differing value, and treat
digits that are part of a name (`phase N`, `conv-NN`, `bNNN`, a leading label) as part of the key.

## Report honesty

- "115 at `d73b6ae`", "133 at `fe71ff1`" and "15 of 18 fail, 3 guards": **all reproduce.**
- The live probe (two ingest warnings, exit 0): **reproduces.**
- **The rewritten `test_phase15` n6 assertion is not justified as written.** Flipping the expected
  outcome is right, because N11 requires it. But the rewrite dropped the only check that the two
  phrasings reach one slot. The report says the test "now asserts that both phrasings reach the same
  `cat:relationship_status:caroline` slot". It does not, and the new docstring says that assertion
  lives in `test_phase16.py`. No test there asserts it.

  Proof: a mutant `_fact_slots` that returns `[]` for any "got married" text passes all 133 tests.
  The remaining assertion ("stale single not active") is satisfied by dedupe linking the two "single"
  facts, not by contradiction detection.

  Fix (Polly's call): add
  `assert ("cat:relationship_status:caroline", "married") in _fact_slots("Caroline got married in May 2023")`,
  or assert `f1` is superseded by the married fact, not merely inactive.
- **"Did not verify" is incomplete:** it omits F1 (cross-page scope) and F3 (identifier numbers as
  values). Two of its items are now closed by this review: the dogfood migration (all 366 captures
  keep explicit = 1) and singularisation false merges (none on real data).

## Could not verify

- No LoCoMo or LongMemEval accuracy re-measure (that is `t_f480c1af`). The collateral run measures
  mutations, not answer quality.
- The live extraction covered one 7-capture synthetic conversation, not a real LoCoMo conversation.
  N7's live hit rate on real conversations is unmeasured beyond the misses shown above.
