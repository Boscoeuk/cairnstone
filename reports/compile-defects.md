# Compile defects found by verification (the maintainer)

Verified against `eval/results/cairn-db/conv-26.db` and its captures. These are extraction-quality
defects, distinct from the retrieval and answering problems already measured.

## D1 — Speaker is mistaken for subject (attribution error)

```
TEXT : Melanie plans to become a single parent
QUOTE: You're doing something amazing! Creating a family for those kids is so lovely.
       You'll be an awesome mom!
CAPTURE (speaker Melanie): ... You'll be an awesome mom! Good luck!
```

Melanie is congratulating **Caroline**. The fact is about Caroline, but it was attributed to
Melanie because Melanie authored the capture. The extractor is treating the utterance author as
the subject of every claim.

This is the most damaging defect found so far, because attribution errors are invisible: the
citation is valid, the quote is verbatim, the fact is well-formed, and the claim is about the
wrong person. A reader checking the quote sees support for the sentence, not for the
attribution.

Required rule: a fact's subject is whoever the claim is about, not whoever said it. When a
speaker praises, describes or addresses someone else, the fact belongs to that person. When the
capture is ambiguous about the subject, the fact must be rejected rather than defaulted to the
speaker.

## D2 — Near-duplicate claims survive as separate facts

```
Caroline plans to become a single parent by adopting kids who need a family
Caroline plans to become a single parent through adoption
```

Dedupe is exact-text only, so paraphrase duplicates both stay active. Policy P7 requires
dedupe by evidence (same claim, same entity), not by wording. The slot-key machinery already
exists in `compile.py` for contradictions and should be reused here.

## D3 — Weak quotes pass the verbatim check

```
TEXT : Caroline plans to become a single parent through adoption
QUOTE: Don't forget to prepare emotionally, since the wait can be hard.
```

The quote is verbatim and the span is real, so the citation-integrity check passes. But the
quote only weakly supports the claim. Verbatim is necessary, not sufficient. A relevance guard
should require the quote to mention the fact's entity or a content token of the claim, and
reject or downgrade otherwise.

## Consequence for measurement

D1–D3 mean some of the 15 "answering failures" may in fact be compile defects surfacing at
answer time. Before tuning the answerer further, the corpus must be re-measured after these
three fixes, otherwise answering improvements will be credited for repairing extraction errors.
