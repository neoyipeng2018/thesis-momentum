# Source qualification

Use this procedure in `scout` mode. Qualification is an explicit manual seam,
not a score inferred from popularity or selected wins.

## Build the profile

Resolve the source's canonical identity and venue. Record its feeds, domains,
bounded `declared_scopes`, and the evidence IDs supporting the assessment. Review
archive coverage, attribution, incentives, and conflicts before deciding, but do
not invent undeclared profile fields for them; preserve relevant support in
`EvidenceCapture` records referenced by `qualification_evidence_ids`.

Start a new `SourceProfile` with `qualification_status: probationary`. The stable
`source_id` derives from the canonical venue.

## Manual decision

A `qualified` profile requires:

- at least one declared scope and qualification evidence ID;
- `assessor` and `assessment_method`;
- timezone-aware `assessed_at` and `review_due_at`;
- `review_due_at > assessed_at`.

Every qualification evidence capture must have `retrieved_at <= assessed_at`;
the assessment cannot rely on evidence that had not yet been captured.

Do not use `quote_only_legacy` as qualification evidence: case checking rejects
it. Qualification applies only to the exact declared scopes. A future assessment
or expired review does not mutate the stored status, but time-aware routing and
checking treat the source as not current.

## Scout terminal states

The router returns sorted source IDs with exactly one state:

- `discovery_exhausted` when no profiles exist;
- `awaiting_manual_qualification` when any profile is probationary;
- `source_qualified` when none is probationary and at least one is qualified;
- `source_rejected` when profiles exist but none is probationary or qualified.

The router reports stored state; it does not promote, reject, or renew a profile.
Never silently cross the manual seam while running `full`.
