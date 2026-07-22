# V2 record contracts

Read this reference before every mode. All records use `schema_version: "2.0"`,
reject undeclared fields, trim string whitespace, and are immutable after model
construction.

## Shared values

- Source status: `probationary`, `qualified`, `suspended`, `rejected`.
- Assertion provenance: `stated`, `inferred`, `assumed`, `missing`.
- Evidence verdict: `supports`, `refutes`, `insufficient`, `unverified`.
- Evidence kind: `primary`, `secondary`, `quote_only_legacy`.
- Material completeness: `full`, `preview`, `unknown`.
- Attribution quality: `direct`, `author_interview`, `quoted_secondary`,
  `reconstructed`.
- Expression origin: `source`, `researcher`; direction: `long`, `short`.
- Research disposition: `unscorable`, `no_actionable_thesis`,
  `insufficient_material`, `reject`, `watch`,
  `validated_trade_candidate`.
- Trigger operator: `lt`, `lte`, `gt`, `gte`, `eq`, `published`,
  `not_published`, `changes`.

All stored timestamps must be timezone-aware. Stable IDs are content-derived:
`source_id` from canonical venue; `episode_id` from source, artifact URL,
publication time, and content hash; `evidence_id` from URL, quote, retrieval time,
and content hash; `case_id` from source, episode, and opening time; and
`candidate_id` from the successful check digest.

## SourceProfile

Fields:

- `source_id`, `name`, and canonical `venue`;
- zero or more `feeds` and `domains`;
- zero or more `declared_scopes`;
- `qualification_status` and `qualification_evidence_ids`;
- optional `assessor`, `assessment_method`, `assessed_at`, and `review_due_at`.

A `qualified` profile requires at least one declared scope and qualification
evidence ID plus non-null assessor, method, assessment time, and review due time.
`review_due_at` must follow `assessed_at`. The manual workflow owns the status
transition; the model does not score or promote sources. Checking also requires
every referenced qualification capture to have been retrieved no later than
`assessed_at`.

## ResearchEpisode

Fields:

- `episode_id`, `source_id`, `artifact_url`, and `title`;
- `published_at`, `retrieved_at`, and `content_sha256`;
- `completeness` and `attribution_quality`;
- zero or more `supplement_evidence_ids`.

`retrieved_at` cannot precede `published_at`. A candidate requires
`completeness: full`; `preview` and `unknown` fail closed. Candidate checking also
rejects `attribution_quality: reconstructed`; `direct`, `author_interview`, and
`quoted_secondary` are accepted by that gate.

## EvidenceCapture

Fields:

- `evidence_id`, `url`, exact `quote`, and `content_sha256`;
- `retrieved_at` and optional `published_at`;
- `capture_kind`.

`published_at`, when known, cannot follow `retrieved_at`. The capture records
provenance, not entailment; assertions own evidence verdicts. A
`quote_only_legacy` capture cannot qualify a source or support a candidate's
load-bearing assertion or catalyst.

## ResearchCase and nested records

An `Assertion` has `assertion_id`, `statement`, `provenance`, optional
`source_quote`, `verdict`, `evidence_ids`, and `load_bearing`. A `stated`
assertion requires a source quote. A `supports` or `refutes` verdict requires at
least one evidence ID.

An `Expression` has `instrument`, `direction`, a typed `horizon`, `origin`,
instrument/direction/horizon provenance, `rationale`, and optional
`source_quote`. Horizons are one of:

- `{kind: sessions, sessions}`;
- `{kind: date, by_date}`;
- `{kind: event, event, by_date}`.

A source-origin expression requires all three dimension provenances to be
`stated` and requires a source quote. A researcher-origin expression may use
other known provenances, but a candidate rejects `missing` on any dimension. A
candidate's date or event horizon must be later than case `as_of` and no later
than `valid_until`.

A `Catalyst` has `description`, `by_date`, `provenance`, and `evidence_ids`. A
`MonitoringTrigger` has `description`, `metric`, `operator`, `target_value`,
timezone-aware `review_at`, and `evidence_ids`.

`ResearchCase` fields:

- `case_id`, `source_id`, `episode_id`, and `scope`;
- `opened_at` and `as_of`;
- one `disposition` and non-empty `disposition_reason`;
- optional `thesis`, `expectations_gap`, `downside`, `countercase`, `expression`,
  `catalyst`, `watch_trigger`, and `valid_until`;
- zero or more `assertions` and `invalidators`.

`as_of` cannot precede `opened_at`. Candidate-specific optional fields become
mandatory at check time; a valid `watch` disposition instead requires a future
dated measurable `watch_trigger`.

## CheckResult

Fields:

- `checker_version`, `case_id`, and case `disposition`;
- canonical input `digest`;
- `valid`, `publishable`, and zero or more `issues`.

Each issue contains `code`, `path`, and `message`. `valid` is true exactly when
issues are empty. `publishable` can be true only for a valid
`validated_trade_candidate` disposition. Checking is deterministic and performs
no writes.

## ValidatedCandidate

Fields:

- `candidate_id`, `case_id`, `source_id`, `scope`, `episode_id`, and fixed
  disposition `validated_trade_candidate`;
- `check_digest`, `checker_version`, `published_at`, and `valid_until`;
- `thesis`, `expectations_gap`, `downside`, `countercase`, and `assertions`;
- one `expression`, one `catalyst`, one or more `invalidators`, and the complete
  referenced `evidence_ids` manifest.

Construction is permitted only through digest-bound publication. The model
requires a future validity window, a supported load-bearing assertion with known
provenance, an evidenced catalyst with known provenance, known expression
provenance, invalidators, and every evidence ID referenced by its assertions,
catalyst, and invalidators. Undeclared portfolio, order, execution, sizing,
performance, and position-management fields are rejected. All candidate-exposed
text is rejected when it contains an allocation, order-execution,
conviction-sizing, or position-management instruction. This includes source
quotes and every referenced `EvidenceCapture.quote` at check and render time.

Publication requires a timezone-aware time satisfying
`case.as_of <= published_at < valid_until`. At that time the source must still be
qualified for the case scope, the catalyst date must still be in the future, and
every invalidator review must still be pending. Any date or event expression
horizon must also still be in the future.

## Relationships

```text
SourceProfile 1 -- * ResearchEpisode
ResearchEpisode 1 -- * ResearchCase
EvidenceCapture * -- * ResearchCase
ResearchCase 1 -- 1 CheckResult per canonical input set
publishable CheckResult 1 -- 0..1 ValidatedCandidate
```

V2 has no `CandidateReview` record and no record-level revision relationship.
Leave a published candidate unchanged; material new research uses a fresh episode
and research case.
