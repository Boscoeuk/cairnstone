# Compile policies

This is the design document for Cairn's behaviour: what enters a brain, where it goes, what it
links to, when it comes back, and when it is retired. Code implements these rules; the eval
harness scores them. Thresholds live in `config/policies.yml` and are tuned by measurement, not
by taste.

## P1 — Capture is immutable

A capture is the raw evidence: a chat turn, a file, a URL, an agent session log. It is stored
with a SHA-256 over its content and never edited. Corrections arrive as new captures. Everything
downstream cites captures by id and character span.

## P2 — No uncited fact

Every fact carries `capture_id`, `span_start`, `span_end` and an immutable `quote` copied from
that span at write time. A fact whose quote cannot be located verbatim in its capture is
**rejected**, not guessed at. Rejections are counted and reported; a compile run that rejects
more than `max_reject_rate` (default 0.25) is treated as a failure of the extractor, not of the
corpus, and stops rather than writing a thin brain.

## P3 — The model proposes, code disposes

The extractor returns JSON. Nothing the model says is trusted structurally: the JSON shape is
validated, and spans are computed by deterministic search, never by the model's arithmetic.
TensorFold 1.0.7 has no constrained decoding, so validation and a single strict retry are the
only defence; a second failure records the capture as `extract_failed` and moves on.

## P4 — Placement is by entity kind, not by topic similarity

Buckets are fixed: `people`, `projects`, `decisions`, `customers`, `misc`. A fact belongs to the
page for the entity it is *about* — the person, the project, the customer — not the page that
happens to share vocabulary. Placement confidence below `min_placement_confidence` (default 0.6)
sends the fact to `misc` with a `placement_uncertain` flag rather than to a wrong page.

## P5 — Claims, not transcripts

A page holds claims: short, atomic, in the present tense where the fact is still true, with
absolute dates. "Ships Mar 31" becomes "Billing v2 ships 2026-03-31". Relative time is resolved
against the capture's own timestamp at compile time. This is a measured requirement: the phase-0
harness caught the answerer replying "Yesterday" to a question whose gold answer was a date.

## P6 — Contradiction supersedes, never overwrites

Two active facts on one page with the same subject and slot but different values are a
contradiction. The newer capture wins; the older is marked `superseded` with `superseded_by` set
to the replacement, and a `fact.superseded` event is written. Both remain readable. Nothing is
deleted, ever. If the two captures have the same timestamp, the contradiction is flagged for
review and neither is superseded — ambiguity is recorded, not resolved by coin flip.

## P7 — Dedupe by evidence, not by wording

Two facts are duplicates when they assert the same claim about the same entity, even if phrased
differently. Dedupe keeps the earliest capture as the canonical citation and records later
captures as corroboration. It does not delete the later facts; it links them.

## P8 — Re-entry is earned

A fact resurfaces in a brief only when it is (a) relevant to the question, (b) currently active,
and (c) not superseded. Retrieval ranks by lexical and vector match, then by recency of
corroboration, then by the entity's importance in the graph. Pinned facts bypass ranking. Stale
facts decay: after `stale_after_days` (default 180) without corroboration, a fact is marked
`stale`, stays readable, and stops being surfaced unless the question asks about history.

## P9 — Briefs are prefix-stable

A compiled brief is assembled as: stable canonical content first, in its own leading message;
the volatile question after it. Byte-identical stable content across calls is what lets
TensorFold reuse a cached prompt — measured as a drop from 26 s to 0.12 s time to first token.
Briefs must therefore not contain timestamps, request ids or counters in the stable portion.
Budget: `brief_token_budget` (default 4000) tokens, hard-capped, with citations trimmed before
claims are.

## P10 — Refusal is a valid answer

If the brain has no active fact that answers the question, the answer is "not recorded", with the
nearest pages offered. Adversarial LoCoMo questions reward this. A confident answer built from a
superseded or stale fact is a defect, not a feature.

## P11 — Nightly evolution is bounded and observable

The evolution pass merges, supersedes, retires and re-scores. It is idempotent, writes a
`change_events` row for every mutation, and records engine telemetry per call. It yields to
interactive traffic: it reads TensorFold's `/health` and backs off while
`live.connections` approaches the engine's `--parallel` limit. A run that mutates more than
`max_mutation_rate` (default 0.2) of a brain's facts in one pass is halted for review, because
mass mutation usually means a policy bug rather than a changed world.

## P12 — Local only

No policy may introduce a cloud call. If a local endpoint is unreachable the pass fails loudly
and resumes from the last completed capture. Degrading to a cloud model is forbidden; degrading
to fewer facts is allowed.
