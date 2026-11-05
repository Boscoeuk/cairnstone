# Phase 2 — independent review (the maintainer)

Worker delivered: `src/cairn/llm.py`, `src/cairn/compile.py`, 11 tests, live smoke (7 facts,
0 uncited). Accepted **after correction**. Three deviations from `docs/compile-policies.md`
were found by review, not by its own tests:

1. **P5 (absolute dates) was not implemented.** The extractor never received the capture
   timestamp, so relative expressions survived compilation. Phase 0 had already proved this
   fails: the harness answered "Yesterday" where the gold answer was 7 May 2023. Fixed: the
   capture timestamp is passed to extraction, the prompt requires YYYY-MM-DD, and the quote
   must come from the capture text, not the timestamp line.
   Verified live: capture stamped 8 May 2023 → "I went to a LGBTQ support group yesterday"
   compiled to "Caroline attended an LGBTQ support group on 2023-05-07".
2. **P7 (corroboration, not deletion) was violated.** `dedupe` set duplicates to `retracted`,
   which asserts a claim was withdrawn when it was merely repeated. Fixed: duplicates stay
   `active` and carry `duplicate_of`; canonical reads and export exclude them.
3. **Contradiction detection was too coarse.** Keying on "text before the last number" made
   "Alice has 2 cats" and "Alice has 3 dogs" contradictory, and missed month-name dates.
   Fixed: the key is the text with value tokens replaced, the value is the token tuple —
   different slots no longer collide, and "ships Mar 31" vs "ships Apr 30" is caught.

Also added: code-fence tolerance in JSON parsing (TensorFold has no constrained decoding, so
this reduces pointless retries without accepting prose).

Verification: 33 tests pass (15 store + 18 compile, 7 written by me). Live smoke: 10 captures,
9 facts, 0 rejected, 0 uncited, 2 pages.

Known limitation, to be measured not asserted: extraction quality is uneven — some facts are
weak paraphrase ("Melanie complimented a painting and asked..."). Citation integrity is solid;
claim quality is the next thing the eval harness must score.
