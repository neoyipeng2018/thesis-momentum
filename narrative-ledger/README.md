# narrative-ledger

`narrative-ledger` is a source-to-candidate research workflow. It discovers and
manually qualifies credible public research sources, captures their work,
independently underwrites a thesis, and stops at a
`validated_trade_candidate`.

The v2 product is research only. It does not size, allocate, execute, or manage
positions.

## Workflow

```text
scout -> explicit qualification seam -> scan -> underwrite -> check
                                                        |-> refusal or watch
                                                        `-> publishable result
                                                              |
                                                        explicit publish
                                                              |
                                                        candidate -> report
```

The five router modes are:

| Mode | Result |
| --- | --- |
| `scout` | Qualification state for the stored source profiles |
| `scan` | `episodes_captured` or `no_episodes_captured` for a qualified-source window |
| `underwrite` | A deterministic check result for one stored research case |
| `monitor` | Current, refresh-due, expired, or fail-closed candidate status |
| `full` | `scout`, `scan`, then `underwrite`, stopping at the first terminal state |

Router modes are read-only. They do not qualify a source, capture a new episode,
publish a candidate, or adjudicate new monitoring evidence.

## CLI

Install the package and run the deterministic seams from this directory:

```bash
python -m pip install -e '.[dev]'
ledger scout
ledger scan \
  --start 2026-07-01T00:00:00Z \
  --end 2026-07-22T00:00:00Z \
  --as-of 2026-07-22T00:00:00Z
ledger underwrite records/research/<case-id>.json
ledger check records/research/<case-id>.json
ledger publish-candidate records/research/<case-id>.json \
  --expect-digest <digest-from-check> \
  --published-at 2026-07-22T12:00:00Z
ledger monitor --as-of 2026-07-22T13:00:00Z
ledger candidates --as-of 2026-07-22T13:00:00Z
ledger render-candidate records/candidates/<candidate-id>.json \
  --output reports/<candidate-id>.html
```

`full` also requires a case plus `--start`, `--end`, and `--as-of`. None of the
router commands publishes a candidate. Only `publish-candidate` writes a
candidate record, and it refuses a stale check digest.

## Domain records

- `SourceProfile` stores identity, venue, feeds, domains, declared scopes, and
  explicit qualification metadata.
- `ResearchEpisode` stores one content-hashed artifact with publication and
  retrieval times, completeness, attribution quality, and supplement evidence
  IDs.
- `EvidenceCapture` stores a quote, URL, timestamps, content hash, and one of
  `primary`, `secondary`, or `quote_only_legacy`.
- `ResearchCase` stores fresh underwriting, one disposition, and its reason.
- `CheckResult` is a pure deterministic result with issues and a content digest.
- `ValidatedCandidate` is the sole successful published endpoint and persists
  the scope in which its source was qualified.

Every assertion retains provenance as `stated`, `inferred`, `assumed`, or
`missing`. A researcher may propose an expression, but it is labelled
`researcher` and never attributed to the source.

## Qualification is manual

Every migrated source starts `probationary`. A source becomes `qualified` only
through an explicit user decision backed by qualification evidence, one or more
declared scopes, an assessor, an assessment method, `assessed_at`, and a future
`review_due_at`. Every qualification capture must have been retrieved by
`assessed_at`. Direct underwriting cannot bypass this seam.

Automated source scoring is outside v2. Popularity, follower count, and a curated
list of past wins are not qualification evidence by themselves.

## Checking and publication

Checking and publication are separate:

1. `check` evaluates the source profile, episode, referenced evidence, and
   research case without writing anything. It returns the case disposition,
   issues, checker version, publishability, and a digest.
2. A candidate can pass only from a currently qualified source and an in-scope
   episode whose `completeness` is `full` and whose `attribution_quality` is not
   `reconstructed`.
3. `publish-candidate` requires the exact digest. Edited inputs make the digest
   stale. It also rechecks source qualification, candidate scope, catalyst,
   invalidators, and any dated expression horizon at publication time;
   publication must be no earlier than the case `as_of` and earlier than
   `valid_until`. Repeat publication returns the existing candidate unchanged.
4. Candidate HTML renders only from a published `ValidatedCandidate`, using the
   template packaged inside the installed `ledger` package.

All text that a candidate can expose, including source quotes and referenced
evidence quotes, is rejected when it contains allocation, order-execution,
conviction-sizing, or position-management instructions.

The research dispositions are `unscorable`, `no_actionable_thesis`,
`insufficient_material`, `reject`, `watch`, and
`validated_trade_candidate`. Empty candidate output is a valid result.

## Migration and fresh start

The v2 cutover preserves only raw research material:

- original artifacts, supplements, URLs, hashes, and source timestamps;
- legacy evidence quotes, URLs, and retrieval timestamps, marked
  `quote_only_legacy` and left unadjudicated;
- real source identities and feeds, imported as probationary profiles.

Migrated episodes are deliberately `completeness: unknown` and
`attribution_quality: direct`. They cannot pass the candidate gate until fresh
research establishes a complete artifact. Prior claims, judgments, scores,
candidate states, technical snapshots, and generated reports are discarded.

```bash
ledger migrate-v2          # dry run: print status, digest, and actions
ledger migrate-v2 --apply  # write verified v2 records and delete v1 derived files
ledger fresh-start         # dry run: list derived v2 records and reports to clear
ledger fresh-start --apply
```

Migration is deterministic and leaves original raw run files unchanged. The
manifest temporarily records `migration_partial` while derived v1 deletion is
pending, finishes as `migration_complete`, and fails closed with
`migration_blocked_integrity_error` on an integrity conflict. See
`references/migration.md` for the exact policy.

## Skill files

`SKILL.md` contains routing, shared invariants, and completion criteria.
Mode-specific procedures live in `references/`:

- `source_qualification.md`
- `signal_capture.md`
- `underwriting.md`
- `candidate_gate.md`
- `monitoring.md`
- `migration.md`
- `contracts.md`

## Verification

```bash
python -m mypy
python -m pytest tests -q
```

The suite covers qualification and temporal gates, episode completeness and
attribution, checker purity, digest locality, stale publication,
atomic/idempotent writes, candidate-only rendering, router stops, deterministic
migration, interrupted migration recovery, and repeatable fresh starts.

---

Research process, not investment advice.
