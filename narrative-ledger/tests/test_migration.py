from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ledger.migrate import MigrationConflictError, fresh_start, migrate_v1
from ledger.models import EvidenceCapture, ResearchEpisode, SourceProfile, source_id_for


def _write_v1(root: Path) -> None:
    config = root / "config"
    config.mkdir(parents=True)
    (config / "watchlist.yaml").write_text(
        """defaults:
  recency_days: 30
sources:
  - id: real-source
    name: Real Source
    kind: rss
    feed: https://example.com/feed
    venue: https://example.com/
  - id: example-bluesky
    name: Example Macro Writer
    kind: bluesky
    handle: example.bsky.social
  - id: x-manual
    name: X account (manual)
    kind: manual
"""
    )
    run = root / "runs" / "2026-07-03_real-source"
    run.mkdir(parents=True)
    (run / "artifact.md").write_bytes(b"# Original thesis\n\nRaw bytes.\n")
    (run / "supplement_1.md").write_bytes(b"# Supplement\n\nMore raw bytes.\n")
    (run / "sources.json").write_text(
        json.dumps(
            {
                "source_id": "real-source",
                "source_name": "Real Source",
                "venue": "https://example.com/",
                "artifact_url": "https://example.com/thesis",
                "title": "Original thesis",
                "published_at": "2026-06-24T13:09:19+00:00",
                "content_sha": "legacy-short-hash",
                "supplements": [
                    {
                        "url": "https://regulator.example.org/release",
                        "sha": "legacy-supplement-hash",
                        "retrieved_at": "2026-07-04T08:11:53+00:00",
                    }
                ],
            },
            indent=2,
        )
    )
    (run / "payload.json").write_text(
        json.dumps(
            {
                "created_at": "2026-07-02T16:51:55Z",
                "claims": [
                    {
                        "id": "c1",
                        "restatement": "Derived judgment must disappear.",
                        "load_bearing": True,
                        "verdict": "supports",
                        "evidence": [
                            {
                                "url": "https://regulator.example.org/release",
                                "quote": "The exact legacy quote.",
                                "retrieved_at": "2026-07-02T16:46:00Z",
                                "is_primary": True,
                            }
                        ],
                    }
                ],
                "priced_in": {
                    "gap_score": 0.9,
                    "inputs": [
                        {
                            "value": 100,
                            "evidence": {
                                "url": "https://market.example.org/quote",
                                "quote": "100.00",
                                "retrieved_at": "2026-07-02T16:56:00Z",
                                "is_primary": False,
                            },
                        }
                    ],
                },
                "decision": {"verdict": "size", "conviction": 1.0, "size_frac": 0.1},
                "brief": {"headline": "Derived"},
                "outcome": {"hit": True},
                "forecast": None,
            },
            indent=2,
        )
    )
    (run / "technicals.json").write_text('{"rsi14": 70}')
    (run / "report.html").write_text("<html>derived report</html>")
    ledger = root / "ledger"
    ledger.mkdir()
    (ledger / "calls.csv").write_text("run_id,ticker\nlegacy,AAA\n")
    (ledger / "source_scores.json").write_text('{"real-source": 0.99}')


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_migration_dry_run_is_pure_and_omits_placeholder_sources(tmp_path: Path) -> None:
    _write_v1(tmp_path)
    before = _tree_bytes(tmp_path)

    result = migrate_v1(tmp_path, dry_run=True)

    assert _tree_bytes(tmp_path) == before
    assert result.status == "migration_complete"
    assert json.loads(result.manifest_json)["status"] == "migration_complete"
    assert result.source_ids == (source_id_for("https://example.com/"),)
    assert result.episode_count == 1
    assert result.evidence_count == 2
    assert not (tmp_path / "records").exists()


def test_migration_preserves_only_raw_material_and_probationary_profiles(
    tmp_path: Path,
) -> None:
    _write_v1(tmp_path)
    source_run = tmp_path / "runs" / "2026-07-03_real-source"
    raw_before = {
        name: (source_run / name).read_bytes()
        for name in ("artifact.md", "supplement_1.md", "sources.json")
    }

    migrate_v1(tmp_path, dry_run=False)

    raw_run = tmp_path / "records" / "raw" / source_run.name
    for name in ("artifact.md", "supplement_1.md", "sources.json"):
        assert (raw_run / name).read_bytes() == (source_run / name).read_bytes()
        assert (source_run / name).read_bytes() == raw_before[name]
    assert sorted(path.name for path in raw_run.iterdir()) == [
        "artifact.md",
        "sources.json",
        "supplement_1.md",
    ]

    profile_paths = sorted((tmp_path / "records" / "sources").glob("*.json"))
    v2_source_id = source_id_for("https://example.com/")
    assert [path.name for path in profile_paths] == [f"{v2_source_id}.json"]
    assert SourceProfile.model_validate_json(profile_paths[0].read_text()).source_id == (
        v2_source_id
    )
    profile = json.loads(profile_paths[0].read_text())
    assert profile == {
        "schema_version": "2.0",
        "assessed_at": None,
        "assessment_method": "v1_migration",
        "assessor": None,
        "declared_scopes": [],
        "domains": ["example.com"],
        "feeds": ["https://example.com/feed"],
        "name": "Real Source",
        "qualification_evidence_ids": [],
        "qualification_status": "probationary",
        "review_due_at": None,
        "source_id": v2_source_id,
        "venue": "https://example.com/",
    }

    episode_paths = sorted((tmp_path / "records" / "episodes").glob("*.json"))
    assert len(episode_paths) == 1
    assert ResearchEpisode.model_validate_json(episode_paths[0].read_text()).source_id == (
        v2_source_id
    )
    episode = json.loads(episode_paths[0].read_text())
    assert set(episode) == {
        "artifact_url",
        "attribution_quality",
        "completeness",
        "content_sha256",
        "episode_id",
        "published_at",
        "retrieved_at",
        "schema_version",
        "source_id",
        "supplement_evidence_ids",
        "title",
    }
    assert episode["source_id"] == v2_source_id
    assert episode["title"] == "Original thesis"
    assert episode["published_at"] == "2026-06-24T13:09:19Z"
    assert episode["retrieved_at"] == "2026-07-02T16:51:55Z"
    assert episode["completeness"] == "unknown"
    assert episode["attribution_quality"] == "direct"
    assert len(episode["content_sha256"]) == 64
    assert len(episode["supplement_evidence_ids"]) == 1

    evidence_paths = sorted((tmp_path / "records" / "evidence").glob("*.json"))
    assert len(evidence_paths) == 2
    assert all(
        EvidenceCapture.model_validate_json(path.read_text()).capture_kind
        == "quote_only_legacy"
        for path in evidence_paths
    )
    captures = [json.loads(path.read_text()) for path in evidence_paths]
    assert {capture["quote"] for capture in captures} == {
        "The exact legacy quote.",
        "100.00",
    }
    assert {capture["retrieved_at"] for capture in captures} == {
        "2026-07-02T16:46:00Z",
        "2026-07-02T16:56:00Z",
    }
    assert {capture["capture_kind"] for capture in captures} == {
        "quote_only_legacy"
    }
    assert all(
        set(capture)
        == {
            "capture_kind",
            "content_sha256",
            "evidence_id",
            "published_at",
            "quote",
            "retrieved_at",
            "schema_version",
            "url",
        }
        for capture in captures
    )
    evidence_text = "".join(path.read_text() for path in evidence_paths)
    for forbidden in (
        "is_primary",
        "verdict",
        "load_bearing",
        "gap_score",
        "conviction",
        "size_frac",
    ):
        assert forbidden not in evidence_text

    records_text = "\n".join(
        path.read_text(errors="replace")
        for path in sorted((tmp_path / "records").rglob("*"))
        if path.is_file()
    )
    for discarded_value in (
        "Derived judgment must disappear.",
        '"rsi14": 70',
        "derived report",
        "legacy,AAA",
    ):
        assert discarded_value not in records_text

    assert (tmp_path / "records" / "migration-manifest.json").is_file()
    assert list((tmp_path / "records" / "research").glob("*.json")) == []
    assert list((tmp_path / "records" / "candidates").glob("*.json")) == []
    assert not any(
        path.exists()
        for path in (
            source_run / "payload.json",
            source_run / "technicals.json",
            source_run / "report.html",
            tmp_path / "ledger" / "calls.csv",
            tmp_path / "ledger" / "source_scores.json",
        )
    )


def test_migration_is_deterministic_idempotent_and_never_mutates_raw_inputs(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_v1(first)
    _write_v1(second)
    source_run = first / "runs" / "2026-07-03_real-source"
    first_raw_before = {
        name: (source_run / name).read_bytes()
        for name in ("artifact.md", "supplement_1.md", "sources.json")
    }

    dry_run_result = migrate_v1(first, dry_run=True)
    first_result = migrate_v1(first, dry_run=False)
    first_records = _tree_bytes(first / "records")
    repeated_result = migrate_v1(first, dry_run=False)
    second_result = migrate_v1(second, dry_run=False)

    assert dry_run_result == first_result == repeated_result == second_result
    assert _tree_bytes(first / "records") == first_records
    assert _tree_bytes(second / "records") == first_records
    assert all(
        (source_run / name).read_bytes() == content
        for name, content in first_raw_before.items()
    )


def test_fresh_start_clears_only_v2_research_candidates_and_reports(
    tmp_path: Path,
) -> None:
    _write_v1(tmp_path)
    migrate_v1(tmp_path, dry_run=False)
    research = tmp_path / "records" / "research" / "case.json"
    candidate = tmp_path / "records" / "candidates" / "candidate.json"
    report = tmp_path / "reports" / "candidate.html"
    retained_report_note = tmp_path / "reports" / "README.txt"
    research.write_text('{"derived": true}')
    candidate.write_text('{"derived": true}')
    report.parent.mkdir()
    report.write_text("<html>derived</html>")
    retained_report_note.write_text("keep")
    preserved_before = {
        path: path.read_bytes()
        for path in (
            next((tmp_path / "records" / "raw").rglob("artifact.md")),
            next((tmp_path / "records" / "sources").glob("*.json")),
            next((tmp_path / "records" / "episodes").glob("*.json")),
            next((tmp_path / "records" / "evidence").glob("*.json")),
            tmp_path / "records" / "migration-manifest.json",
        )
    }

    dry_run_result = fresh_start(tmp_path, dry_run=True)

    assert dry_run_result.removed == (
        "records/candidates/candidate.json",
        "records/research/case.json",
        "reports/candidate.html",
    )
    assert all(path.exists() for path in (research, candidate, report))

    applied_result = fresh_start(tmp_path, dry_run=False)

    assert applied_result == dry_run_result
    assert not any(path.exists() for path in (research, candidate, report))
    assert retained_report_note.read_text() == "keep"
    assert all(path.read_bytes() == content for path, content in preserved_before.items())
    assert fresh_start(tmp_path, dry_run=False).removed == ()


def test_migration_conflict_fails_before_writing_any_other_record(tmp_path: Path) -> None:
    _write_v1(tmp_path)
    conflict = (
        tmp_path
        / "records"
        / "raw"
        / "2026-07-03_real-source"
        / "artifact.md"
    )
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"different bytes")
    before = _tree_bytes(tmp_path / "records")

    with pytest.raises(MigrationConflictError, match="unmanifested v2 record"):
        migrate_v1(tmp_path, dry_run=False)

    assert _tree_bytes(tmp_path / "records") == before


def test_manifest_accounts_for_every_preserved_discarded_and_omitted_input(
    tmp_path: Path,
) -> None:
    _write_v1(tmp_path)

    result = migrate_v1(tmp_path, dry_run=False)
    manifest = json.loads(
        (tmp_path / "records" / "migration-manifest.json").read_text()
    )
    actions = manifest["actions"]

    assert manifest["manifest_sha256"] == result.manifest_sha256
    assert manifest["status"] == "migration_complete"
    assert manifest["integrity_problems"] == []
    assert {
        action["source"]
        for action in actions
        if action["kind"] == "preserve_raw"
    } == {
        "runs/2026-07-03_real-source/artifact.md",
        "runs/2026-07-03_real-source/sources.json",
        "runs/2026-07-03_real-source/supplement_1.md",
    }
    assert {
        action["source"]
        for action in actions
        if action["kind"] == "discard_derived"
    } == {
        "ledger/calls.csv",
        "ledger/source_scores.json",
        "runs/2026-07-03_real-source/payload.json",
        "runs/2026-07-03_real-source/report.html",
        "runs/2026-07-03_real-source/technicals.json",
    }
    assert {
        action["reason"]
        for action in actions
        if action["kind"] == "discard_derived"
    } == {"derived_or_contaminated_v1_state"}
    assert {
        action["source"]
        for action in actions
        if action["kind"] == "omit_placeholder"
    } == {
        "config/watchlist.yaml#example-bluesky",
        "config/watchlist.yaml#x-manual",
    }
    assert {
        action["reason"]
        for action in actions
        if action["kind"] == "omit_placeholder"
    } == {"placeholder_source_identity"}
    assert [item["source"] for item in manifest["raw_files"]] == [
        "runs/2026-07-03_real-source/artifact.md",
        "runs/2026-07-03_real-source/sources.json",
        "runs/2026-07-03_real-source/supplement_1.md",
    ]
    assert sorted(
        origin
        for origins in manifest["evidence_provenance"].values()
        for origin in origins
    ) == [
        "runs/2026-07-03_real-source/payload.json#/claims/0/evidence/0",
        "runs/2026-07-03_real-source/payload.json#/priced_in/inputs/0/evidence",
    ]
    episode_id = next(iter(manifest["episode_retrieval_provenance"]))
    assert manifest["episode_retrieval_provenance"][episode_id] == {
        "basis": "legacy_payload_created_at",
        "source": "runs/2026-07-03_real-source/payload.json#/created_at",
    }


def test_episode_retrieval_falls_back_to_publication_time_with_provenance(
    tmp_path: Path,
) -> None:
    _write_v1(tmp_path)
    payload_path = tmp_path / "runs" / "2026-07-03_real-source" / "payload.json"
    payload = json.loads(payload_path.read_text())
    del payload["created_at"]
    payload_path.write_text(json.dumps(payload, indent=2))

    migrate_v1(tmp_path, dry_run=False)

    episode_path = next((tmp_path / "records" / "episodes").glob("*.json"))
    episode = ResearchEpisode.model_validate_json(episode_path.read_text())
    assert episode.retrieved_at == episode.published_at
    manifest = json.loads(
        (tmp_path / "records" / "migration-manifest.json").read_text()
    )
    assert manifest["episode_retrieval_provenance"][episode.episode_id] == {
        "basis": "source_published_at_fallback",
        "source": "runs/2026-07-03_real-source/sources.json#/published_at",
    }


def test_manifest_write_is_atomic_and_cleans_temporary_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_v1(tmp_path)
    real_replace = os.replace

    def fail_manifest_replace(source: str | Path, destination: str | Path) -> None:
        if Path(destination).name == "migration-manifest.json":
            raise OSError("simulated interrupted manifest publication")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_manifest_replace)

    with pytest.raises(OSError, match="simulated interrupted manifest publication"):
        migrate_v1(tmp_path, dry_run=False)

    records = tmp_path / "records"
    assert not (records / "migration-manifest.json").exists()
    assert list(records.glob(".migration-manifest.json.*.tmp")) == []
    assert (tmp_path / "runs" / "2026-07-03_real-source" / "payload.json").exists()
    assert (tmp_path / "ledger" / "calls.csv").exists()


def test_interrupted_first_output_write_can_resume_without_a_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_v1(tmp_path)
    real_replace = os.replace
    canonical_writes = 0

    def interrupt_after_first_output(
        source: str | Path, destination: str | Path
    ) -> None:
        nonlocal canonical_writes
        real_replace(source, destination)
        target = Path(destination)
        if "records" in target.parts and target.name != "migration-manifest.json":
            canonical_writes += 1
            if canonical_writes == 1:
                raise OSError("simulated interruption after first canonical write")

    monkeypatch.setattr(os, "replace", interrupt_after_first_output)

    with pytest.raises(OSError, match="after first canonical write"):
        migrate_v1(tmp_path, dry_run=False)

    records = tmp_path / "records"
    assert not (records / "migration-manifest.json").exists()
    assert len(tuple(path for path in records.rglob("*") if path.is_file())) == 1

    monkeypatch.undo()
    result = migrate_v1(tmp_path, dry_run=False)

    assert result.status == "migration_complete"
    assert (records / "migration-manifest.json").is_file()
    assert not (tmp_path / "runs" / "2026-07-03_real-source" / "payload.json").exists()


def test_failed_canonical_output_verification_never_deletes_v1_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_v1(tmp_path)
    real_replace = os.replace

    def corrupt_source_replace(source: str | Path, destination: str | Path) -> None:
        real_replace(source, destination)
        target = Path(destination)
        if target.parent.name == "sources":
            target.write_bytes(b"corrupt canonical output")

    monkeypatch.setattr(os, "replace", corrupt_source_replace)

    with pytest.raises(MigrationConflictError, match="failed verification"):
        migrate_v1(tmp_path, dry_run=False)

    assert not (tmp_path / "records" / "migration-manifest.json").exists()
    assert (tmp_path / "runs" / "2026-07-03_real-source" / "payload.json").exists()
    assert (tmp_path / "ledger" / "calls.csv").exists()


def test_migration_blocks_when_v2_derived_state_already_exists(tmp_path: Path) -> None:
    _write_v1(tmp_path)
    candidate = tmp_path / "records" / "candidates" / "candidate.json"
    candidate.parent.mkdir(parents=True)
    candidate.write_text('{"candidate": "must not survive cutover"}')
    before = _tree_bytes(tmp_path)

    with pytest.raises(MigrationConflictError) as caught:
        migrate_v1(tmp_path, dry_run=False)

    assert caught.value.status == "migration_blocked_integrity_error"
    blocked_manifest = json.loads(caught.value.manifest_json)
    assert blocked_manifest["status"] == "migration_blocked_integrity_error"
    assert "records/candidates/candidate.json" in blocked_manifest[
        "integrity_problems"
    ][0]
    assert _tree_bytes(tmp_path) == before


def test_in_memory_target_collision_blocks_before_any_write(tmp_path: Path) -> None:
    _write_v1(tmp_path)
    watchlist = tmp_path / "config" / "watchlist.yaml"
    watchlist.write_text(
        watchlist.read_text()
        + """  - id: duplicate-venue
    name: Conflicting Identity
    kind: rss
    feed: https://example.com/other-feed
    venue: https://example.com/
"""
    )

    with pytest.raises(MigrationConflictError, match="duplicate migration target"):
        migrate_v1(tmp_path, dry_run=False)

    assert not (tmp_path / "records").exists()


def test_duplicate_legacy_source_id_blocks_before_any_write(tmp_path: Path) -> None:
    _write_v1(tmp_path)
    watchlist = tmp_path / "config" / "watchlist.yaml"
    watchlist.write_text(
        watchlist.read_text()
        + """  - id: real-source
    name: Ambiguous Source
    kind: rss
    feed: https://different.example/feed
    venue: https://different.example/
"""
    )

    with pytest.raises(MigrationConflictError, match="duplicate legacy source id"):
        migrate_v1(tmp_path, dry_run=False)

    assert not (tmp_path / "records").exists()


def test_first_migration_rejects_unmanifested_v2_state(tmp_path: Path) -> None:
    _write_v1(tmp_path)
    rogue = tmp_path / "records" / "sources" / "rogue.json"
    rogue.parent.mkdir(parents=True)
    rogue.write_text('{"qualification_status": "qualified"}')
    before = _tree_bytes(tmp_path)

    with pytest.raises(MigrationConflictError, match="unmanifested v2 record"):
        migrate_v1(tmp_path, dry_run=False)

    assert _tree_bytes(tmp_path) == before


def test_repeat_migration_rejects_unmanifested_v2_state(tmp_path: Path) -> None:
    _write_v1(tmp_path)
    migrate_v1(tmp_path, dry_run=False)
    rogue = tmp_path / "records" / "evidence" / "rogue.json"
    rogue.write_text('{"capture_kind": "primary"}')
    before = _tree_bytes(tmp_path)

    with pytest.raises(MigrationConflictError, match="unmanifested v2 record"):
        migrate_v1(tmp_path, dry_run=False)

    assert _tree_bytes(tmp_path) == before


def test_incomplete_run_blocks_instead_of_silently_leaving_derived_state(
    tmp_path: Path,
) -> None:
    _write_v1(tmp_path)
    incomplete = tmp_path / "runs" / "2026-07-04_incomplete"
    incomplete.mkdir()
    (incomplete / "payload.json").write_text('{"decision": "discard me"}')
    before = _tree_bytes(tmp_path)

    with pytest.raises(MigrationConflictError, match="missing artifact.md"):
        migrate_v1(tmp_path, dry_run=False)

    assert _tree_bytes(tmp_path) == before


def test_deletion_failure_leaves_partial_manifest_and_can_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_v1(tmp_path)
    real_unlink = Path.unlink

    def fail_technicals_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == "technicals.json":
            raise OSError("simulated derived-state deletion failure")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_technicals_unlink)

    with pytest.raises(OSError, match="derived-state deletion failure"):
        migrate_v1(tmp_path, dry_run=False)

    manifest_path = tmp_path / "records" / "migration-manifest.json"
    partial_manifest = json.loads(manifest_path.read_text())
    assert partial_manifest["status"] == "migration_partial"
    assert partial_manifest["integrity_problems"] == [
        "derived v1 deletion pending"
    ]
    assert (tmp_path / "runs" / "2026-07-03_real-source" / "technicals.json").exists()

    monkeypatch.undo()
    result = migrate_v1(tmp_path, dry_run=False)

    assert result.status == "migration_complete"
    assert json.loads(manifest_path.read_text())["status"] == "migration_complete"
    assert not (tmp_path / "runs" / "2026-07-03_real-source" / "technicals.json").exists()
