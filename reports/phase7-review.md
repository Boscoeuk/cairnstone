# Phase 7 — verified (the maintainer)

Numbers reproduce: cairn **78.3%** at 1,109 tokens (median 2.60 s), multi-hop 65.0%, temporal
88.2%, retrieval 3 / answering 10 failures. 62 tests pass.

## The attribution fix works, in both directions

Verified against `eval/results/cairn-db/conv-26.db`:

```
30 | people/caroline | active | Caroline is single
31 | people/caroline | active | Caroline plans to become a single parent and make a family...
151| people/melanie | active | Melanie is married
```

"Caroline is married" is gone — rejected at extraction as `subject_mismatch`, so the contradiction
was prevented rather than superseded. Preventing is better than repairing here: no wrong fact ever
entered the brain.

I then checked the **other** direction, which is the risk of an over-strict validator: are valid
second-person facts still being attributed correctly to the listener? They are. Every remaining
second-person-only attribution on a people page is correct:

| fact | quote | verdict |
|---|---|---|
| Caroline held an event on 2023-06-09 | "Sounds like your event was amazing!" | correct — listener is Caroline |
| Caroline is transgender | "You've come a long way since your transition" | correct |
| Caroline is transitioning | "How have your friends and fam been helping you out..." | correct |
| Mel is using art to express herself | "art is helping you express yourself" | correct |

So the rule distinguishes speaker from listener rather than blanket-rejecting second person. That
is the behaviour the brief required.

## Rejection volume is high and needs watching

122 rejections in total (subject_mismatch 61, weak_quote 33, subject_unresolved 27, quote-not-found
1), against 807 facts kept. Fact count fell from 528 to 426 on conv-26.

Accuracy did not fall (75.0% → 78.3%), so the rejections were not visibly harmful on this scope.
But `weak_quote` (33) is the riskiest category: a legitimate paraphrase may share no content token
with its quote and be discarded. It should be audited before the corpus grows, because recall loss
on a bigger corpus would be silent.

## Still open

- Multi-hop 65.0% vs full_context 75.0%; commonsense 50.0% vs 75.0%. Inference across turns is
  still the weakness of a flat fact set.
- 10 answering failures remain, all with gold support present in the brief.
