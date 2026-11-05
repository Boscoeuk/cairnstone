# Phase 6 — verified, with three new compile defects (the maintainer)

Phase 6's reported numbers reproduce exactly (75.0% / 1,256 tokens / 2.84 s; 52 tests pass), and
its stated defect is genuinely fixed: "Melanie plans to become a single parent" is gone from the
recompiled brain, replaced by first-person-supported "Melanie is a parent".

## Verified cache finding

Phase 6 recorded 0% prompt-cache hits and flagged it without explanation. I measured the engine
directly:

| stable prefix | prompt tokens | cached tokens | TTFT |
|---|---|---|---|
| ~110 tokens, two different questions | 92 / 93 | 0 / 0 | 3.26 s → 0.44 s |
| ~1,500 tokens, two different questions | 2,666 / 2,667 | 0 → **2,650** | 5.42 s → **0.22 s** |

The stable prefix is byte-identical across questions (confirmed by calling `build_brief` twice),
but TensorFold's cache does not engage at ~100-token prefixes. There is a size threshold between
~92 and ~2,666 prompt tokens. Phase 6's 0% is therefore a consequence of choosing a small entity
directory, not a prefix-stability bug. At 2.8 s latency the trade is acceptable, but the 200x TTFT
win requires a large stable prefix — the two goals conflict and should be stated, not rediscovered.

## New defects found in the recompiled corpus (not fixed by phase 6)

**D1b — second-person addressee attributed to the speaker.** Phase 6 fixed the "speaker praising
the listener" case for atomic attributes, but not the general rule:

```
CAPTURE: Caroline: Wow, what an amazing family pic! How long have you been married?
FACT   : Caroline is married
```

Caroline is *asking Melanie* about Melanie's marriage. The fact belongs to Melanie. Meanwhile the
brain also holds "Caroline is single" — so the corpus contains a flat contradiction about
Caroline's marital status, and no supersede fired.

**D2 — near-duplicate claims survive.** Four active facts all assert the same thing:
"Caroline plans to become a single parent", "...by adopting kids who need a family",
"...through adoption" (twice). Dedupe is exact-text only; policy P7 requires dedupe by claim.

**D3 — quotes that barely support the claim.**
`"Caroline was not married as of 2023-07-15"` is cited to the quote *"I wish I had known you back
then!"* — verbatim, correctly spanned, and almost irrelevant. Verbatim is necessary, not
sufficient.

**D4 — non-numeric contradictions are invisible.** "Caroline is single" vs "Caroline is married"
never superseded, because the slot-key machinery only recognises number and date values. The
single-vs-married conflict is the exact case the product exists to handle.

## Consequence

The 75.0% is measured on a corpus that still contains wrong attributions and flat contradictions.
Some of the 12 remaining "answering failures" may be these defects surfacing at answer time.
Phase 7 fixes the extraction layer before any further answering work.
