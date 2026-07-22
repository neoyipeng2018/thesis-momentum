# Raw-only v2 migration

Use this procedure only for the v1 cutover or a derived-state fresh start. The
migration copies raw run material into v2 records and leaves the original raw run
files unchanged.

## Preserve and construct

For every complete v1 run, migration preserves byte-identical `artifact.md`,
`sources.json`, and `supplement_*.md` files under `records/raw/<run-id>/`.
Canonical URLs and publication metadata create a content-addressed
`ResearchEpisode`.

Migration also creates:

- real watchlist sources as `probationary` profiles with
  `assessment_method: v1_migration` and no declared scope or qualification
  evidence;
- episodes with `completeness: unknown` and
  `attribution_quality: direct`;
- legacy payload quotes as `quote_only_legacy` evidence with their URL and
  retrieval time, no publication time, and a quote-content hash;
- a manifest mapping legacy source IDs, raw-file hashes, evidence origins,
  episode retrieval-time provenance, and every action.

Episode `retrieved_at` comes from the legacy payload `created_at` when available;
otherwise it falls back to the source publication time. The manifest records
which basis was used. A migrated episode cannot pass the candidate gate while
its completeness remains `unknown`, and legacy quote-only evidence cannot be
used for qualification, a load-bearing assertion, or a candidate catalyst.

## Omit and discard

Placeholder watchlist identities are omitted. Migration deletes only these
recognized v1 derived files when present:

- `runs/*/payload.json`, `runs/*/technicals.json`, and `runs/*/report.html`;
- `ledger/calls.csv` and `ledger/source_scores.json`.

The raw artifact, source metadata, and supplement files remain in both their
original run location and the verified v2 raw copy. Prior claims, verdicts,
scores, decisions, candidate state, technical snapshots, and generated reports
are not imported as v2 research.

## Commands and status semantics

```bash
ledger migrate-v2
ledger migrate-v2 --apply
ledger fresh-start
ledger fresh-start --apply
```

`ledger migrate-v2` is a dry run. It prints a prospective
`migration_complete` status, counts, manifest digest, and ordered actions without
writing or deleting files. `--apply` verifies every target, writes canonical
records, verifies their bytes, and then deletes recognized v1 derived files.

During an applied migration with derived files to delete, the on-disk manifest
first has `status: migration_partial` and the integrity problem
`derived v1 deletion pending`. Only after all deletions verify does it change
atomically to `migration_complete` with no integrity problems. A later apply can
resume from that partial manifest.

An invalid input, incomplete run, conflicting target, altered manifest,
unmanifested v2 state, existing v2 research/candidate/report output, duplicate
legacy source ID, or other integrity conflict raises
`migration_blocked_integrity_error`. The CLI writes the blocked manifest JSON to
standard error and exits with status 2 without applying a partial plan.

Repeat migration is idempotent. After legacy payload deletion, it reconstructs
quote-only evidence and retrieval provenance from the verified manifest and v2
records. If execution stops before the first manifest write, a retry accepts only
the exact planned canonical files already written and completes the cutover. A
completed manifest rejects newly reappearing v1 derived state.

## Fresh start

`fresh-start` lists, and `fresh-start --apply` deletes, only:

- `records/research/*.json`;
- `records/candidates/*.json`;
- `records/reports/*.html`;
- `reports/*.html`.

It preserves raw runs, source profiles, episodes, evidence captures, and the
migration manifest. Repeating it after the derived state is empty reports zero
removals.
