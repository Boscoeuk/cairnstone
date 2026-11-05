# Phase 8 — verified (the maintainer)

Numbers reproduce: n=150 (conv-26 75, conv-30 75), cairn **76.0%** at 1,204 tokens, median 2.64 s;
full_context 53.3% at 13,278; naive_rag 45.3% at 932. 69 tests pass.

The larger sample weakens the point estimate from 78.3% (n=60) to 76.0% (n=150) without
overturning the ranking. The margin over full_context is +22.7 points and over naive_rag +30.7
points at 1/11th the tokens. That is now a defensible claim rather than a directional one.

## Dialogue context worked on multi-hop

Phase 7: multi-hop 65.0% vs full_context 75.0%. Phase 8: **67.5% vs 57.3%** — cairn now *wins*
multi-hop instead of losing it. Adding bounded dialogue windows around cited spans was the right
fix, and it cost ~95 tokens of brief (1,109 → 1,204).

## Single-hop regressed, and the cause is answering, not retrieval

Cairn scores 68.4% on single-hop where full_context and naive_rag both score 76.3%. That is
backwards — single-hop is the case a fact store should win. I audited all 12 failures:

**Refusal with the evidence present (the largest cluster).**
- "What is Jon's favorite style of dance?" — gold "Contemporary"; the brain holds "Jon loves all
  dances, but contemporary is his top pick"; answer was **"Not recorded."**
- "What did Gina find for her clothing store on 1 February, 2023?" — brain holds "Gina has a new
  store"; answer "Not recorded."
- "What did Jon and Gina compare their entrepreneurial journeys to?" — support present; answer
  "Not recorded."

**Wrong item chosen from several valid facts.** "What did Gina design for her store?" — gold "the
space, furniture, and decor"; the brain holds both the space fact and the furniture fact; the
answer was "A chandelier", a different fact on the same page.

**Genuine compile gaps.** "What does Gina say about the dancers in the photo?" (gold "They look
graceful") and "How does Gina describe the feeling that dance brings?" (gold "magical") have no
fact in the brain at all — the adjectives were never extracted as claims.

So single-hop is not a retrieval problem: the evidence is in the brief and the answerer either
refuses or picks the wrong item. This is the `Not recorded` instruction being over-applied.

## Caveats carried forward

- The relaxed `weak_quote` guard was verified on scratch DBs only; the eval corpus still reflects
  the stricter guard (807 facts, 33 weak-quote rejections). Applying it needs a recompile.
- Commonsense (54.5% vs naive_rag's 90.9% at n=11) remains cairn's weakest category; n=11 is too
  small to conclude much, but the direction is unfavourable and should be watched, not dismissed.
