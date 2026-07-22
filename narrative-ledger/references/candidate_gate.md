# Candidate gate

A `ResearchCase` already carries one disposition. The gate validates that case
against its exact source profile, episode, and referenced evidence. Checking and
publication are separate operations.

## Check

`check_case(case, profile, episode, evidence)` is pure. Its digest covers the
checker version, complete profile, complete episode, complete case, and every
referenced evidence capture in deterministic order. Unreferenced registry
evidence does not change the digest. Conflicting captures sharing an evidence ID
produce a deterministic issue.

The case disposition is one of:

- `unscorable`;
- `no_actionable_thesis`;
- `insufficient_material`;
- `reject`;
- `watch`;
- `validated_trade_candidate`.

Every case requires consistent source and episode IDs, a qualified in-scope
source whose assessment is effective at `as_of`, and every referenced evidence
capture to be available. A `watch` additionally requires a measurable
`watch_trigger` whose `review_at` is after the case `as_of`.

## Candidate hard gates

A `validated_trade_candidate` is publishable only when all of these pass:

- the source qualification is current at the case `as_of`, the scope is
  declared, qualification evidence is not `quote_only_legacy`, and every
  qualification capture was retrieved by `assessed_at`;
- the episode was retrieved no later than `as_of`, has `completeness: full`, and
  does not have `attribution_quality: reconstructed`;
- every referenced evidence capture was retrieved no later than `as_of`;
- `thesis`, `expectations_gap`, `downside`, and `countercase` are present;
- an expression is present and its instrument, direction, and horizon
  provenances are not `missing`; a date or event horizon is later than `as_of`
  and no later than `valid_until`;
- a catalyst is present, its provenance is not `missing`, it cites evidence, and
  that evidence is not `quote_only_legacy`; its date is later than `as_of`;
- at least one assertion is `load_bearing`; every load-bearing assertion has
  known provenance, a `supports` verdict, and at least one `primary` evidence
  capture, with no `quote_only_legacy` support;
- at least one typed invalidator has `review_at` after `as_of`;
- `valid_until` is present and after `as_of`;
- every candidate-exposed text value, including source quotes and all referenced
  evidence quotes, contains no allocation, order-execution, conviction-sizing,
  or position-management instruction.

Candidate records may describe the instrument, direction, research horizon,
catalyst, thesis, expectations gap, downside, countercase, assertions, evidence,
validity window, and invalidators. They reject undeclared fields, including
allocation, order, execution, conviction-sizing, performance-attribution, and
position-management instructions.

## Publish

Publish only with the exact digest from a successful, publishable check.
Publication reruns the check, rejects changed inputs, derives `candidate_id` from
the digest, and requires a timezone-aware publication time satisfying
`case.as_of <= published_at < valid_until`. The source must still be qualified
for the case scope, the catalyst date must be later than the publication date,
every invalidator review must be later than `published_at`, and a dated
expression horizon must not be stale. Publication then writes atomically.
Repeating it returns the exact bound existing record without rewriting it; a
model-valid but altered record is a conflict.

Render candidate output only from the published `ValidatedCandidate`, never from
a `ResearchCase`, failed check, or legacy payload.
