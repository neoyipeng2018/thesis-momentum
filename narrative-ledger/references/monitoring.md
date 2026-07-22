# Candidate monitoring

Monitor the temporal research status of published candidates. This mode never
allocates, orders, executes, attributes performance, or manages a position.

## Active candidates

A candidate is active at timezone-aware `as_of` only when:

- its source profile exists and has `qualification_status: qualified`;
- `assessed_at <= as_of`;
- the profile has `review_due_at >= as_of`;
- the candidate's persisted `scope` remains in the profile's declared scopes;
- `published_at <= as_of < valid_until`.

The router does not modify a candidate or source profile.

## Due research

An active candidate returns `research_refresh_required` when either:

- `catalyst.by_date <= as_of.date()`; or
- any invalidator has `review_at <= as_of`.

The result contains the IDs of active candidates with a due trigger. Monitoring
does not fetch evidence, decide whether an invalidator fired, or rewrite the
candidate. Capture material new research in a fresh `ResearchEpisode` and
`ResearchCase`, then run underwriting and checking again.

## Terminal states

The router returns exactly one state:

- `no_active_candidates` when no candidate records exist;
- `research_refresh_required` when an active candidate has a due catalyst or
  invalidator;
- `candidate_current` when at least one candidate is active and none has a due
  trigger;
- `source_qualification_suspended` when no candidate is active and any candidate
  lacks a source profile or its source is not currently qualified. This label is
  the fail-closed aggregate for missing, unqualified, not-yet-effective, or
  review-expired profiles and for a candidate whose scope is no longer declared;
- `candidate_expired` when no candidate is active, every source is current, and
  every candidate has reached `valid_until`;
- `monitoring_incomplete` for the remaining no-active case, such as a candidate
  whose publication time is still in the future.

V2 does not implement `CandidateReview` or `candidate_invalidated`. The original
candidate remains immutable; a fresh case is the only route for adjudicating new
research.
