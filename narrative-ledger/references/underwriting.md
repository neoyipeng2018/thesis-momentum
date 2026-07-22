# Independent underwriting

Use this procedure for one stored `ResearchEpisode`. Produce a fresh
`ResearchCase`; never inherit legacy claims or verdicts.

## Build assertions

Reconstruct the causal spine from premise to conclusion. Each `Assertion`
records:

- `assertion_id` and plain-language `statement`;
- provenance: `stated`, `inferred`, `assumed`, or `missing`;
- `source_quote` when provenance is `stated`;
- verdict: `supports`, `refutes`, `insufficient`, or `unverified`;
- `evidence_ids` and whether the assertion is `load_bearing`.

Verification may change the verdict; it never changes provenance. A
`supports` or `refutes` verdict must cite evidence. Every load-bearing candidate
assertion must be supported with known provenance and at least one `primary`
capture; `quote_only_legacy` is not eligible.

## Retrieve symmetrically

Seek the strongest supporting and disconfirming evidence. Prefer the originator
of a fact: regulator, filing, statistical agency, exchange disclosure, or data
originator. Company material is interested primary evidence and may need
corroboration.

Each `EvidenceCapture` stores an exact quote, URL, content hash, retrieval time,
optional publication time, and `capture_kind` of `primary`, `secondary`, or
`quote_only_legacy`. It does not own the assertion verdict. If evidence is
unavailable or does not entail the assertion, use `insufficient`; do not rewrite
the claim to make it pass.

## Case-level judgment

State the thesis, explicit expectations gap, downside, and strongest countercase
in their corresponding `ResearchCase` fields. These are text fields; v2 does not
define a structured valuation model, reference-class object, or scalar source
score.

When an expression is warranted, record its instrument, `long` or `short`
direction, typed horizon, origin, rationale, and separate provenance for
instrument, direction, and horizon. A source-origin expression requires every
dimension to be `stated` plus a source quote. Otherwise use `researcher` without
altering the source profile.

A candidate case also needs an evidenced catalyst, at least one typed
invalidator, and `valid_until`. A watch case instead needs a measurable
`watch_trigger` with `review_at` after the case `as_of`.

Keep all candidate-exposed text inside the research boundary. Do not include
allocation, order-execution, conviction-sizing, or position-management
instructions in authored fields, source quotes, or referenced evidence quotes.

## Completion criterion

Choose one disposition and give a non-empty `disposition_reason`:
`unscorable`, `no_actionable_thesis`, `insufficient_material`, `reject`, `watch`,
or `validated_trade_candidate`. Then submit the case, exact source profile,
episode, and evidence collection to the pure check described in
`candidate_gate.md`.
