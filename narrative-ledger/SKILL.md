---
name: narrative-ledger
description: Scout and manually qualify public market-research sources, scan
  qualified sources for current research episodes, underwrite a source thesis
  into a validated trade candidate, monitor candidate research validity, or run
  the full source-to-candidate workflow. Use when the user asks to find credible
  market researchers, scan a research watchlist, validate a post, thread,
  letter, interview, or thesis, recheck a candidate, or "run the ledger". The
  workflow ends at a candidate and never sizes, allocates, executes, or manages
  a position.
---

# narrative-ledger

Turn research from explicitly qualified sources into independently validated
trade candidates. Treat an empty candidate list as an honest successful result.

## Route the request

- **scout** — discover a source or inspect its stored qualification state.
- **scan** — find stored episodes from currently qualified sources in a declared
  time window.
- **underwrite** — check one stored research case and return one terminal state.
- **monitor** — report whether a published candidate is current, due for fresh
  research, expired, or fail-closed.
- **full** — run `scout` -> qualification seam -> `scan` -> `underwrite`, stopping
  at the first terminal state.

Read `references/contracts.md` before every mode. Then read only the references
named by that mode.

## Shared invariants

- Start every source as `probationary`. Only an explicit user decision may set
  `qualification_status` to `qualified`, with declared scopes, evidence IDs,
  assessor, assessment method, `assessed_at`, and `review_due_at`.
- Require a currently qualified source whose declared scope covers the case
  before returning `validated_trade_candidate`.
- Keep the source's statement separate from the researcher's interpretation.
  Mark assertion provenance `stated`, `inferred`, `assumed`, or `missing`.
- Mark an expression `source` only when its instrument, direction, and horizon
  are all `stated` and a source quote is present. Otherwise mark it `researcher`;
  it must not alter the source profile.
- Keep episode `published_at`, `retrieved_at`, case `opened_at`, case `as_of`, and
  candidate `published_at` distinct.
- Fail the candidate gate on an episode that is not `full`, has reconstructed
  attribution, was retrieved after the case `as_of`, or relies on unavailable,
  late, or disallowed legacy evidence.
- Reject instructions to allocate, transact, size, or manage a position from
  every candidate-exposed authored field, source quote, and referenced evidence
  quote.
- End at research. Never add allocation, order, execution, conviction-sizing,
  performance-attribution, or position-management instructions.

## Mode contracts

### scout

1. Read `references/source_qualification.md`.
2. Resolve identity, canonical venue, feeds, domains, declared scopes, and the
   evidence supporting a bounded qualification decision.
3. Create or update a `SourceProfile` as `probationary`.
4. Cross the qualification seam only after explicit user approval.

The router returns exactly one of `discovery_exhausted`,
`awaiting_manual_qualification`, `source_qualified`, or `source_rejected`. It
does not mutate a profile or infer trust from popularity.

### scan

1. Read `references/signal_capture.md`.
2. Require timezone-aware `start`, `end`, and `as_of` values satisfying
   `start <= end <= as_of`.
3. Consider only sources that are `qualified` with
   `assessed_at <= as_of <= review_due_at`.
4. Persist each retained artifact as a `ResearchEpisode` with a content hash,
   publication and retrieval times, completeness, attribution quality, and any
   supplement evidence IDs.

The router returns exactly one of `no_qualified_sources`,
`no_episodes_captured`, or `episodes_captured`. It reports only episodes whose
`published_at` is inside the inclusive window and whose `retrieved_at <= as_of`.
It does not validate a thesis or invent an expression.

### underwrite

1. Read `references/underwriting.md` and `references/candidate_gate.md`.
2. Build one fresh `ResearchCase` for a stored episode and recheck source
   qualification and scope.
3. Separate source statements, researcher inferences, assumptions, and missing
   links; retrieve supporting and disconfirming evidence.
4. State the thesis, expectations gap, downside, strongest countercase,
   expression, catalyst, invalidators, validity window, and one disposition
   reason when those fields apply.
5. Submit the case, profile, episode, and evidence captures to `check`.

The router returns `source_not_qualified` for an unqualified or expired source,
`check_failed` for any other invalid result, or the valid case disposition:
`unscorable`, `no_actionable_thesis`, `insufficient_material`, `reject`, `watch`,
or `validated_trade_candidate`.

### monitor

1. Read `references/monitoring.md`.
2. Load published candidates and their current source profiles at a
   timezone-aware `as_of`.
3. Treat a due catalyst date or invalidator review time as a request for fresh
   research; do not adjudicate it inside the router.
4. Route material new research through a fresh episode and research case. Leave
   the published candidate immutable.

The router returns exactly one of `no_active_candidates`, `candidate_current`,
`research_refresh_required`, `candidate_expired`,
`source_qualification_suspended`, or `monitoring_incomplete`. V2 has no
`CandidateReview` record and no `candidate_invalidated` terminal state.

### full

The CLI form accepts an existing research case plus the scan window. Require the
case `as_of` to equal the full-run `as_of`. Scout only the case's source; an
unrelated probationary source does not block it. Stop unless that source returns
`source_qualified` and scan returns `episodes_captured`. Underwrite only when the
case episode is among the scanned episode IDs. Never qualify a source or publish
a candidate.

## Check and publish

- `check` is pure: identical canonical inputs return the same `CheckResult` and
  digest without changing the filesystem.
- A successful candidate check returns `publishable: true`; it does not create a
  draft or candidate record.
- `publish-candidate` is a separate explicit action. It requires the exact digest
  returned by `check`, rejects edited inputs, requires
  `case.as_of <= published_at < valid_until`, and rechecks qualification plus due
  catalyst, invalidator, and dated-horizon research at the candidate publication
  time.
- Publication is atomic and idempotent. Render only from the resulting
  `ValidatedCandidate`.

## Conditional references

- Read `references/migration.md` only for v1 cutover or fresh-start work.
- Read `references/contracts.md` for exact record fields, enums, and
  relationships.
