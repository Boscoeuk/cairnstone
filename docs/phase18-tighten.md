# Phase 18 tightening (rev 3) — quantity slot precision

Part A landed at `f0495b6`: 225 tests pass, supersessions returned (probe 0/13/39 -> 5/86/39). But the
quantity slot over-fires: **67 of the 112 probe flags are `cat:qty` false positives**. Fix precision
before Part B, or Tes will reject on noise alone.

## The failure, measured

These are real flags the current code produces on the dogfood and LME brains. Every one is wrong: the
two facts assert different attributes, not competing values for one attribute.

    cat:qty:tensorfold:token:count
      a: TensorFold cold prefill processes 4,588 tokens in 9.19 s (~500 tok/s)
      b: TensorFold caches 0 tokens for a single concatenated user message ...
    cat:qty:sample:question:count
      a: The harness had no cap on question count; a 3-sample run is ~600 questions ...
      b: The naive_rag eval run on 1 sample with 12 questions ...
    cat:qty:accuracy:token:count
      a: The full_context backend scored 83.3% accuracy at 15,043 tokens.
      b: The naive_rag backend scored 66.7% accuracy at 770 tokens.
    cat:qty:mean:context:count
      a: The full_context backend scored 83.3% accuracy with mean 15,043 context tokens ...
      b: The naive_rag backend scored 66.7% accuracy with mean 770 context tokens ...
    cat:qty:dubai:include:count
      a: Day 2 of the Dubai trip (April 23, 2023) includes Jumeirah Beach ...
      b: Day 3 of the Dubai trip (April 24, 2023) includes Global Village ...

Three defects cause all of them: the slot fires on numbers inside measurement or prepositional phrases
("at 15,043 tokens", "with mean 770 tokens", "with 2 samples"); the subject and attribute are taken
from the wrong words ("sample", "mean", "accuracy", "include"); and day/ordinal numbers ("Day 2")
are treated as counts.

## Required rules (implement all, with tests)

1. **Direct-object quantity only, for counts.** A count slot fires only when the number is followed
   directly by a noun, allowing exactly one `of` between them ("2 of Emma's recipes"). A number inside
   a prepositional phrase other than a time phrase must NOT fire: reject "at 15,043 tokens",
   "with 2 samples", "with mean 770 tokens", "in 9.19 s".
2. **Counting verb required.** The verb governing the quantity must be in the closed counting set
   (own, have, bought, purchase, got, read, watch, run, try, visit, attend, complete, spend, save,
   earn, score, collect, lead, take, eat, drink, play, write, paint, make, do). If the number is not
   the object of one of these verbs, no count slot.
3. **Ordinals and day numbers are not counts.** Reject a number that follows a capitalised
   noun-label ("Day 2", "Phase 11", "Part 3", "Step 2", "Episode 4") or that ends in st/nd/rd/th.
4. **Attribute is the counted noun, not the nearest word.** Take the head noun of the object phrase
   after the number, skipping prepositions and possessives ("2 of Emma's recipes" -> `recipe`;
   "three tops from H&M" -> `top`). The subject must be the pre-verbal grammatical subject via
   `_subject_prefix`, never a word inside the object.
5. **Durations**: fire only on `<subject> <verb> [object] for/about <number> <time-unit>`, with the
   attribute being the object head noun when present, otherwise the subject ("Luna has been with her
   owner for about 6 months" -> attribute `luna`; "The user has had Luna for about 9 months" ->
   attribute `luna`), and the value in days.
6. **Frequencies**: fire only on `once|twice|<n> times a|per <period>` or `every <n?> <period>`, with
   the attribute being the activity head noun, and the value normalised to per-week.
7. **One slot per fact maximum** for quantity. A fact that asserts several quantities keys on the
   first direct-object or duration/frequency quantity and must not emit extra qty slots for
   incidental numbers.

## Tests (fail before, pass after, mutant proof each)

- The five false-positive pairs above must produce **no** flag. Mutant: restore the loose
  "any number" rule, each test fails.
- The Emma, H&M, Yoga, Luna and Dr Smith update pairs must still supersede. Mutant: disable qty
  slots, they fail.
- `Day 2` / `Day 3` Dubai facts: no qty slot at all.
- Suite stays green (225 passed at `f0495b6`).

## Evidence to return

Probe on the 27 databases: report superseded / flagged / duplicates_linked against the current
`5/86/39` and the phase-17 baseline `0/13/39`. Expect superseded to stay at or above 5 and flagged to
fall sharply. Name every remaining `cat:qty` flag and say whether it is genuine. Append to
`reports/phase18-report.md` as "Revision 2 — precision". Commit on `main` with the repo's `.venv/bin/python`; do not add allow entries.
