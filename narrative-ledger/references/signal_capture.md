# Signal capture

Use this procedure in `scan` mode. Capture what the source published before
interpreting whether it is correct.

## Window and qualification

Require timezone-aware `start`, `end`, and `as_of` with
`start <= end <= as_of`. A source is eligible only when it is `qualified` with
`assessed_at <= as_of <= review_due_at`.

The router considers a stored episode when its source is eligible, its
`published_at` is inside the inclusive start/end window, and its
`retrieved_at <= as_of`. It returns `no_qualified_sources`,
`no_episodes_captured`, or `episodes_captured`. An empty capture result makes no
judgment about whether a thesis is actionable.

## Episode record

Persist each retained artifact as one immutable `ResearchEpisode` with exactly:

- `source_id`, `artifact_url`, and `title`;
- `published_at` and `retrieved_at`;
- a SHA-256 `content_sha256` from the raw artifact;
- `completeness`: `full`, `preview`, or `unknown`;
- `attribution_quality`: `direct`, `author_interview`, `quoted_secondary`, or
  `reconstructed`;
- any `supplement_evidence_ids`.

The stable `episode_id` derives from source ID, artifact URL, publication time,
and content hash. Retrieval cannot precede publication. Identical records with
the same stable ID deduplicate; conflicting records with the same ID fail
closed.

## Completeness and attribution

Treat subscription prompts, trailing “Read more” links, abrupt endings, and
suspicious brevity as preview signals. Use `unknown` when the available material
does not establish completeness.

Search for fuller public attribution in this order:

1. the author's complete public artifact;
2. a public interview in which the author states the thesis;
3. named coverage carrying a direct quotation.

Capture supporting material as `EvidenceCapture` records and reference their IDs
from the episode. A relayed quotation may establish what the author said; it does
not verify that the statement is correct. Do not turn a paraphrase into an exact
source quotation.

A candidate fails closed unless the episode is `full`. It also fails when
attribution is `reconstructed`; `direct`, `author_interview`, and
`quoted_secondary` pass the attribution-quality gate. Scan itself records and
returns episodes without adjudicating their thesis or inventing an expression.

## Completion criterion

Finish when retained artifacts have stable raw identity, timestamps,
completeness, attribution quality, and supplement evidence references. Assertion
provenance and expression origin belong to the later `ResearchCase`, not the
episode.
