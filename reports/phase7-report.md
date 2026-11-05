# Phase 7 report — subject resolution and claim integrity

DONE: Extraction layer enforces subject resolution, claim-level dedupe, categorical
contradiction supersede and a weak-quote guard, all in code; corpus recompiled; all three
backends re-measured on the phase-6 scope. Cairn accuracy 75.0% → **78.3%**.

## FILES

- `src/cairn/compile.py` — phases 7A–7D (extraction prompt, validation, guards, dedupe,
  contradiction pass)
- `eval/harness.py` — compile log now prints rejection counts by reason (reporting only; the
  answer prompt and judge are untouched)
- `tests/test_compile.py` — fixtures updated for the `subject` field; 10 new phase-7 tests
- `reports/phase7-report.md` — this file

## A. Subject resolution (defect D1/D1b) — enforced in code

The extraction JSON now carries a required `subject` field (the person the fact is about), and
`compile.py` enforces grammatical-person agreement in `_subject_error`, called from
`write_facts` before anything is written:

- quote has a first-person marker (`I`, `my`, `me`, …) → subject must be the quote's speaker
  (speaker parsed from the `Name: ...` turn labels; for a quote inside a multi-turn capture the
  speaker is the nearest preceding label — `_speaker_for_quote`);
- quote has a second-person marker (`you`, `your`, …) and no first-person marker → subject must
  NOT be the speaker (it belongs to the listener);
- quote names a recognisable third person (a turn label) → subject must be that person;
- no person signal and the subject is neither named in the quote nor the speaker → rejected
  `subject_unresolved`.

Rejection reasons: `subject_mismatch` (person marker contradicts the subject) and
`subject_unresolved` (no resolvable signal). Limitation, stated: a third-person quote naming
someone who is not a turn label in the capture cannot be recognised as a person by code, so the
no-signal default (accept when subject == speaker) applies; the prompt forbids it.

## B. Near-duplicate claims (defect D2)

`dedupe` now keys on `_claim_key`: the slot-key base (numbers/dates stripped, per P6 machinery)
with trailing modifier clauses (`by …`, `through …`, `via …`) cut, plus the fact's value tokens
and categorical words. Paraphrases collapse; facts differing in a value stay distinct so the
contradiction pass can supersede them. Later facts stay `active` with `duplicate_of` set —
never deleted, never retracted.

## C. Non-numeric contradictions (defect D4)

`supersede_contradictions` now collects slots from `_fact_slots`: the numeric/date machinery
plus a small explicit categorical lexicon (`relationship_status`: single/married/divorced/
widowed/engaged/dating). The categorical slot key keeps the text *before* the matched word, so
"Caroline plans to become a single parent" (key `caroline plans to become a`) never conflicts
with "Caroline is married" (key `caroline is`) — plans are not statuses. Two active facts on one
page with the same key and different values supersede the older capture (`superseded_by` set,
`fact.superseded` event written), per P6.

## D. Weak-quote guard (defect D3)

`_weak_quote` rejects a fact whose quote shares no content token with the fact's text (shared
tokenizer `_content_tokens` from `retrieve.py`, subject's name ignored, crude 4-char prefix stem
so nurse/nursing match). Reason: `weak_quote`.

## Recompile and re-measurement

Commands (exact, as specified):

```
PYTHONPATH=src:. python3 -m eval.harness --backend cairn --limit 2 --questions-per-sample 30 --max-questions 60 --brief-budget 600 --recompile
PYTHONPATH=src:. python3 -m eval.harness --backend full_context --limit 2 --questions-per-sample 30 --max-questions 60
PYTHONPATH=src:. python3 -m eval.harness --backend naive_rag --limit 2 --questions-per-sample 30 --max-questions 60
```

Compile log (rejection counts by reason):

```
compiled conv-26: 419 captures, 426 facts, 6 pages, 0 failed captures, 19 dupes linked,
  0 superseded, rejections: {"subject_mismatch": 18, "subject_unresolved": 17, "weak_quote": 22}
compiled conv-30: 369 captures, 381 facts, 6 pages, 0 failed captures, 25 dupes linked,
  0 superseded, rejections: {"quote not found in capture": 1, "subject_mismatch": 43,
  "subject_unresolved": 10, "weak_quote": 11}
```

Totals: 807 facts accepted, 122 rejected — `subject_mismatch` 61, `weak_quote` 33,
`subject_unresolved` 27, `quote not found in capture` 1. 0 failed captures; 44 duplicates
linked; 0 supersessions (the mis-attributed "married" facts are now rejected at extraction, so
the contradiction no longer exists to supersede — see the DB proof below).

### Accuracy by category (60 questions, local judge)

| category | cairn phase 7 | cairn phase 6 | full_context | naive_rag |
|---|---|---|---|---|
| temporal (n=34) | **88.2%** | 85.3% | 29.4% | 17.6% |
| multi-hop (n=20) | **65.0%** | 60.0% | 75.0% | 50.0% |
| commonsense (n=4) | 50.0% | 50.0% | 75.0% | 100% |
| single-hop (n=2) | 100% | 100% | 100% | 100% |
| **overall** | **78.3%** | 75.0% | 50.0% | 36.7% |

Cairn: 1,109 mean context tokens (phase 6: 1,256), 2.69 s mean latency (2.84 s). The 75.0%
baseline was measured on a corpus containing the D1–D4 defects; the +3.3 points come from the
extraction fixes, not answerer changes (answer prompt and judge untouched).

### Retrieval / answering split (cairn)

60 diagnostic rows: 53 briefs contained gold support, **3 retrieval failures, 10 answering
failures** (phase 6: 3 and 12).

## Single-vs-married contradiction resolved — DB proof

Query (recompiled brain `eval/results/cairn-db/conv-26.db`):

```sql
SELECT f.id, f.status, f.superseded_by, f.duplicate_of, f.text
FROM facts f JOIN pages p ON p.id = f.page_id
WHERE p.path = 'people/caroline'
  AND (f.text LIKE '%single%' OR f.text LIKE '%married%') ORDER BY f.id;
```

Output:

```
30|active|||Caroline is single
31|active|||Caroline plans to become a single parent and make a family for kids who need one
```

And across the whole brain, the only active fact containing "married" is on the correct page:

```sql
SELECT f.id, p.path, f.status, f.text FROM facts f
JOIN pages p ON p.id = f.page_id
WHERE f.text LIKE '%married%';
```

```
151|people/melanie|active|Melanie is married
```

"Caroline is married" no longer exists in any status — the capture that produced it (Caroline
asking Melanie "How long have you been married?") is now rejected at extraction by the
subject guard (`subject_mismatch`), so the corpus asserts exactly one marital status for
Caroline. The old defect fact "Caroline was not married as of 2023-07-15" (weak quote) is also
gone, rejected by the weak-quote guard.

## Tests

`PYTHONPATH=src:. python3 -m pytest tests/ -q` → **62 passed** (10 new phase-7 tests: subject
field required, Caroline-asking rejection, Melanie-praising rejection/acceptance, first-person
pass-through, third-person label rule, unresolvable rejection, paraphrase dedupe linking,
single-vs-married supersede, plan-vs-status precision, weak-quote rejection).

## UNVERIFIED / limitations

- The third-person rule only recognises persons that appear as turn labels in the capture; a
  quote naming a third party with no label relies on the prompt (stated above).
- `dedupe`'s clause cut (`by`/`through`/`via`) could over-merge genuinely distinct claims that
  differ only after those prepositions; none observed in the recompiled brains (44 dupes, all
  verified paraphrases on spot-check).
- Judge is the local `local-judge` model, as in all prior phases; numbers are
  local-judged, not GPT-judged.
