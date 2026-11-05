# Phase 5 — verification and corrections (the maintainer)

The phase-5 report claims "2 conversations, 60 questions". **That is false.** Both the cairn and
the full_context result files contain 60 rows, all with `sample_id = conv-26`. The runner applied
`--max-questions 60` as a *global* cap and conversation 26 alone had more than 60 questions, so
the second conversation was never reached. The scope was one conversation, 60 questions.

This matters because the margin was presented as holding "across 2 conversations". It held across
60 questions of a single conversation. Still a real improvement over n=12 — but not the claim made.

Three further problems found by verification:

1. **The atomic-fact fix was never exercised.** `conv-26.db` still holds 449 facts, identical to
   phase 3/4, and still contains no atomic relationship-status fact — only "Caroline plans to
   become a single parent". The live run reused the cached DB compiled before the extractor
   prompt changed. The worker said the fix was "tested offline"; it was, and it was not tested
   live. Fixed by re-running with `--recompile`.

2. **The diagnostic mislabelled aggregation failures as retrieval failures.** I audited the 12
   "retrieval failures" against the DB. Several were questions with list-like golds —
   *"What activities does Melanie partake in?"* (gold: pottery, camping, painting, swimming) —
   where the evidence was spread across several facts. The scorer required half the gold's
   *tokens* inside a *single* fact, so it reported "support absent" while the brief plainly
   contained pottery, camping and painting facts. Fixed: list-like golds are scored per item,
   with support counted when half the items are covered anywhere in the brief. The split
   definition changed, so phase-4/5 splits are not directly comparable to later ones.

3. **The split was reported for backends that cannot have one.** `full_context` and `naive_rag`
   showed "28 retrieval failures" and "34 retrieval failures" — artefacts of treating a missing
   `gold_support_in_brief` field as False. Now the split is reported only over rows that carry
   the field, with `diagnostic_rows` stating how many were scored.

4. **`--limit N` did not mean N conversations.** Added `--questions-per-sample`, so coverage is
   real: 2 conversations × 30 questions, not 60 questions from the first.

Genuine findings from phase 5 that survive the corrections:

- Cairn beats full_context and naive_rag on 60 questions from one conversation: 70.0% vs 53.3%
  and 43.3%.
- The win is carried by temporal questions (100% vs 42.9%), which is where cited, date-resolved
  facts should win.
- Cairn **loses** on commonsense (55.6% vs 77.8%) and multi-hop (39.1% vs 56.5%). Raw transcripts
  support cross-turn inference better than a flat fact set. That is a real weakness, not a bug
  to explain away.

Corrected re-run with recompiled brains and real two-conversation coverage is in flight.
