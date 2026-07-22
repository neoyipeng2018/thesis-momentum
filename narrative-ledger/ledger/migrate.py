from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias, cast
from urllib.parse import urlparse

import yaml

from .models import (
    EvidenceCapture,
    ResearchEpisode,
    SourceProfile,
    episode_id_for,
    evidence_id_for,
    source_id_for,
)

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
MigrationActionKind: TypeAlias = Literal[
    "preserve_raw",
    "write_source",
    "write_episode",
    "write_evidence",
    "write_manifest",
    "discard_derived",
    "omit_placeholder",
]
MigrationStatus: TypeAlias = Literal[
    "migration_complete",
    "migration_partial",
    "migration_blocked_integrity_error",
]


@dataclass(frozen=True)
class MigrationAction:
    kind: MigrationActionKind
    source: str | None
    target: str | None
    sha256: str | None
    reason: str | None = None


@dataclass(frozen=True)
class MigrationResult:
    status: MigrationStatus
    source_ids: tuple[str, ...]
    episode_count: int
    evidence_count: int
    manifest_sha256: str
    manifest_json: str
    actions: tuple[MigrationAction, ...]


@dataclass(frozen=True)
class ResetResult:
    removed: tuple[str, ...]


@dataclass(frozen=True)
class _Output:
    path: Path
    content: bytes
    kind: MigrationActionKind
    source: str | None


@dataclass(frozen=True)
class _LegacyEvidence:
    evidence_id: str
    url: str
    quote: str
    retrieved_at: str
    origins: tuple[str, ...]


@dataclass(frozen=True)
class _Plan:
    source_ids: tuple[str, ...]
    source_id_map: tuple[tuple[str, str], ...]
    outputs: tuple[_Output, ...]
    discards: tuple[Path, ...]
    actions: tuple[MigrationAction, ...]
    evidence_provenance: tuple[tuple[str, tuple[str, ...]], ...]
    episode_retrieval_provenance: tuple[tuple[str, str, str], ...]
    episode_count: int
    evidence_count: int


class MigrationConflictError(RuntimeError):
    status: Literal["migration_blocked_integrity_error"] = (
        "migration_blocked_integrity_error"
    )

    def __init__(self, problem: str) -> None:
        super().__init__(problem)
        self.integrity_problems = (problem,)
        body: dict[str, JsonValue] = {
            "schema_version": "2.0",
            "migration": "v1_to_v2_raw_only",
            "status": self.status,
            "integrity_problems": [problem],
        }
        self.manifest_sha256 = _sha256(_json_bytes(body))
        manifest: dict[str, JsonValue] = dict(body)
        manifest["manifest_sha256"] = self.manifest_sha256
        self.manifest_json = _json_bytes(manifest).decode()


def _object(value: JsonValue, context: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _array(value: JsonValue | None, context: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _text(value: JsonValue | None, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _optional_text(value: JsonValue | None, context: str) -> str | None:
    if value is None:
        return None
    return _text(value, context)


def _read_json(path: Path) -> dict[str, JsonValue]:
    return _object(cast(JsonValue, json.loads(path.read_text())), str(path))


def _json_bytes(value: JsonValue) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _model_bytes(record: SourceProfile | ResearchEpisode | EvidenceCapture) -> bytes:
    return f"{record.model_dump_json(indent=2)}\n".encode()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _previous_manifest(root: Path) -> dict[str, JsonValue] | None:
    path = root / "records" / "migration-manifest.json"
    if not path.exists():
        return None
    if not path.is_file():
        raise MigrationConflictError(f"migration manifest is not a file: {path}")
    manifest = _read_json(path)
    recorded_sha256 = _text(
        manifest.get("manifest_sha256"), "migration manifest sha256"
    )
    body = dict(manifest)
    del body["manifest_sha256"]
    if _sha256(_json_bytes(body)) != recorded_sha256:
        raise MigrationConflictError("existing migration manifest failed integrity check")
    return manifest


def _previous_discard_sources(
    manifest: dict[str, JsonValue] | None,
) -> frozenset[str]:
    if manifest is None:
        return frozenset()
    sources: set[str] = set()
    for index, value in enumerate(
        _array(manifest.get("actions"), "migration manifest actions")
    ):
        action = _object(value, f"migration manifest action {index}")
        if action.get("kind") == "discard_derived":
            sources.add(
                _text(action.get("source"), f"migration manifest action {index} source")
            )
    return frozenset(sources)


def _previous_evidence_for_run(
    root: Path, manifest: dict[str, JsonValue], run_id: str
) -> tuple[_LegacyEvidence, ...]:
    provenance = _object(
        manifest.get("evidence_provenance"), "migration evidence provenance"
    )
    prefix = f"runs/{run_id}/payload.json#"
    captures: list[_LegacyEvidence] = []
    for evidence_id, value in sorted(provenance.items()):
        origins = tuple(
            sorted(
                _text(origin, f"evidence provenance {evidence_id}")
                for origin in _array(value, f"evidence provenance {evidence_id}")
            )
        )
        if not any(origin.startswith(prefix) for origin in origins):
            continue
        path = root / "records" / "evidence" / f"{evidence_id}.json"
        if not path.is_file():
            raise MigrationConflictError(f"migrated evidence record is missing: {path}")
        record = EvidenceCapture.model_validate_json(path.read_text())
        if (
            record.capture_kind != "quote_only_legacy"
            or record.published_at is not None
            or record.content_sha256 != _sha256(record.quote.encode())
        ):
            raise MigrationConflictError(
                f"migrated evidence record conflicts with raw-only policy: {path}"
            )
        captures.append(
            _LegacyEvidence(
                evidence_id=record.evidence_id,
                url=str(record.url),
                quote=record.quote,
                retrieved_at=record.retrieved_at.isoformat(),
                origins=origins,
            )
        )
    return tuple(captures)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _timestamp(value: str, context: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} must be an ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"{context} must be timezone-aware")
    return parsed


def _watchlist_sources(root: Path) -> tuple[dict[str, JsonValue], ...]:
    path = root / "config" / "watchlist.yaml"
    watchlist = _object(cast(JsonValue, yaml.safe_load(path.read_text())), str(path))
    return tuple(
        _object(value, f"watchlist source {index}")
        for index, value in enumerate(_array(watchlist.get("sources"), "watchlist sources"))
    )


def _is_placeholder(source: dict[str, JsonValue]) -> bool:
    source_id = _text(source.get("id"), "source id")
    name = _text(source.get("name"), f"source {source_id} name")
    handle = source.get("handle")
    return (
        source_id.startswith("example-")
        or source_id == "x-manual"
        or name.startswith("Example ")
        or handle == "example.bsky.social"
    )


def _profile(source: dict[str, JsonValue]) -> tuple[str, SourceProfile]:
    legacy_source_id = _text(source.get("id"), "source id")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", legacy_source_id) is None:
        raise ValueError(f"invalid source id: {legacy_source_id}")
    feed = _optional_text(source.get("feed"), f"source {legacy_source_id} feed")
    handle = _optional_text(source.get("handle"), f"source {legacy_source_id} handle")
    venue = _optional_text(source.get("venue"), f"source {legacy_source_id} venue")
    if venue is None and feed is not None:
        parsed_feed = urlparse(feed)
        if parsed_feed.scheme and parsed_feed.netloc:
            venue = f"{parsed_feed.scheme}://{parsed_feed.netloc}/"
    if venue is None and handle is not None:
        venue = f"https://bsky.app/profile/{handle}"
    if venue is None:
        raise ValueError(f"source {legacy_source_id} has no venue")
    feeds: list[str] = []
    if feed is not None:
        feeds.append(feed)
    elif handle is not None:
        feeds.append(f"https://bsky.app/profile/{handle}")
    domains: list[str] = []
    for url in (venue, feed):
        if url is None:
            continue
        hostname = urlparse(url).hostname
        if hostname is None:
            continue
        domain = hostname.lower().removeprefix("www.")
        if domain not in domains:
            domains.append(domain)
    profile_data: dict[str, JsonValue] = {
        "source_id": source_id_for(venue),
        "name": _text(source.get("name"), f"source {legacy_source_id} name"),
        "venue": venue,
        "feeds": list(feeds),
        "domains": list(domains),
        "declared_scopes": [],
        "qualification_status": "probationary",
        "qualification_evidence_ids": [],
        "assessor": None,
        "assessment_method": "v1_migration",
        "assessed_at": None,
        "review_due_at": None,
    }
    profile = SourceProfile.model_validate(profile_data)
    return legacy_source_id, profile


def _evidence_value(value: JsonValue, origin: str) -> tuple[tuple[str, str, str], str]:
    evidence = _object(value, origin)
    url = _text(evidence.get("url"), f"{origin} url")
    quote = _text(evidence.get("quote"), f"{origin} quote")
    retrieved_at = _text(evidence.get("retrieved_at"), f"{origin} retrieved_at")
    return (url, quote, retrieved_at), origin


def _legacy_evidence(
    payload: dict[str, JsonValue], payload_path: Path, root: Path
) -> tuple[_LegacyEvidence, ...]:
    by_capture: dict[tuple[str, str, str], list[str]] = {}
    base = _relative(payload_path, root)
    for claim_index, value in enumerate(_array(payload.get("claims", []), "payload claims")):
        claim = _object(value, f"payload claim {claim_index}")
        for evidence_index, evidence in enumerate(
            _array(claim.get("evidence", []), f"claim {claim_index} evidence")
        ):
            origin = f"{base}#/claims/{claim_index}/evidence/{evidence_index}"
            key, recorded_origin = _evidence_value(evidence, origin)
            by_capture.setdefault(key, []).append(recorded_origin)
    priced_in = _object(payload.get("priced_in", {}), "payload priced_in")
    for input_index, value in enumerate(
        _array(priced_in.get("inputs", []), "priced_in inputs")
    ):
        item = _object(value, f"priced_in input {input_index}")
        if "evidence" not in item:
            continue
        origin = f"{base}#/priced_in/inputs/{input_index}/evidence"
        key, recorded_origin = _evidence_value(item["evidence"], origin)
        by_capture.setdefault(key, []).append(recorded_origin)
    captures: list[_LegacyEvidence] = []
    for (url, quote, retrieved_at), origins in sorted(by_capture.items()):
        content_sha256 = _sha256(quote.encode())
        captures.append(
            _LegacyEvidence(
                evidence_id=evidence_id_for(
                    url,
                    quote,
                    _timestamp(retrieved_at, f"{origins[0]} retrieved_at"),
                    content_sha256,
                ),
                url=url,
                quote=quote,
                retrieved_at=retrieved_at,
                origins=tuple(sorted(origins)),
            )
        )
    return tuple(captures)


def _raw_names(run_dir: Path) -> tuple[str, ...]:
    names = ["artifact.md", "sources.json"]
    names.extend(path.name for path in run_dir.glob("supplement_*.md"))
    return tuple(sorted(names))


def _merge_evidence(
    evidence_by_id: dict[str, _LegacyEvidence], capture: _LegacyEvidence
) -> None:
    existing = evidence_by_id.get(capture.evidence_id)
    if existing is None:
        evidence_by_id[capture.evidence_id] = capture
        return
    if (
        existing.url != capture.url
        or existing.quote != capture.quote
        or existing.retrieved_at != capture.retrieved_at
    ):
        raise MigrationConflictError(
            f"conflicting evidence content for {capture.evidence_id}"
        )
    evidence_by_id[capture.evidence_id] = _LegacyEvidence(
        evidence_id=existing.evidence_id,
        url=existing.url,
        quote=existing.quote,
        retrieved_at=existing.retrieved_at,
        origins=tuple(sorted(set(existing.origins + capture.origins))),
    )


def _ensure_empty_v2_derived_state(root: Path) -> None:
    derived_paths = tuple(
        sorted(
            {
                *(root / "records" / "research").glob("*.json"),
                *(root / "records" / "candidates").glob("*.json"),
                *(root / "records" / "reports").glob("*.html"),
                *(root / "reports").glob("*.html"),
            }
        )
    )
    existing = tuple(path for path in derived_paths if path.is_file())
    if existing:
        raise MigrationConflictError(
            "v2 derived state must be empty before migration: "
            + ", ".join(_relative(path, root) for path in existing)
        )


def _ensure_unique_outputs(outputs: tuple[_Output, ...], root: Path) -> None:
    targets: set[Path] = set()
    for output in outputs:
        if output.path in targets:
            raise MigrationConflictError(
                f"duplicate migration target: {_relative(output.path, root)}"
            )
        targets.add(output.path)


def _ensure_manifest_bound_records(
    root: Path,
    outputs: tuple[_Output, ...],
    manifest_present: bool,
) -> None:
    records = root / "records"
    if not records.is_dir():
        return
    if records.is_symlink():
        raise MigrationConflictError(f"v2 records directory is a symlink: {records}")
    existing = {path for path in records.rglob("*") if path.is_file()}
    expected = {output.path: output.content for output in outputs}
    if manifest_present:
        allowed = set(expected)
        allowed.add(records / "migration-manifest.json")
        conflicts = existing - allowed
    else:
        conflicts = {
            path
            for path in existing
            if path not in expected or path.read_bytes() != expected[path]
        }
    if conflicts:
        raise MigrationConflictError(
            "unmanifested v2 record: "
            + ", ".join(
                _relative(path, root) for path in sorted(conflicts)
            )
        )


def _planned_outputs(root: Path) -> _Plan:
    records = root / "records"
    outputs: list[_Output] = []
    discards: list[Path] = []
    actions: list[MigrationAction] = []
    previous_manifest = _previous_manifest(root)
    previous_discard_sources = _previous_discard_sources(previous_manifest)
    recognized_discard_sources: set[str] = set()
    source_ids: list[str] = []
    source_id_map: dict[str, str] = {}
    seen_legacy_source_ids: set[str] = set()
    for source in _watchlist_sources(root):
        legacy_source_id = _text(source.get("id"), "source id")
        if legacy_source_id in seen_legacy_source_ids:
            raise MigrationConflictError(
                f"duplicate legacy source id: {legacy_source_id}"
            )
        seen_legacy_source_ids.add(legacy_source_id)
        if _is_placeholder(source):
            actions.append(
                MigrationAction(
                    "omit_placeholder",
                    f"config/watchlist.yaml#{legacy_source_id}",
                    None,
                    None,
                    "placeholder_source_identity",
                )
            )
            continue
        legacy_source_id, profile = _profile(source)
        source_id_map[legacy_source_id] = profile.source_id
        source_ids.append(profile.source_id)
        outputs.append(
            _Output(
                records / "sources" / f"{profile.source_id}.json",
                _model_bytes(profile),
                "write_source",
                f"config/watchlist.yaml#{legacy_source_id}",
            )
        )

    runs = root / "runs"
    if not runs.is_dir():
        raise MigrationConflictError(f"v1 runs directory not found: {runs}")
    run_dirs = tuple(path for path in sorted(runs.iterdir()) if path.is_dir())
    incomplete_runs = tuple(
        path for path in run_dirs if not (path / "artifact.md").is_file()
    )
    if incomplete_runs:
        raise MigrationConflictError(
            "run directory missing artifact.md: "
            + ", ".join(_relative(path, root) for path in incomplete_runs)
        )
    evidence_by_id: dict[str, _LegacyEvidence] = {}
    episode_retrieval_provenance: list[tuple[str, str, str]] = []
    for run_dir in run_dirs:
        metadata_path = run_dir / "sources.json"
        metadata = _read_json(metadata_path)
        run_id = run_dir.name
        legacy_source_id = _text(metadata.get("source_id"), f"{run_id} source_id")
        source_id = source_id_map.get(legacy_source_id)
        if source_id is None:
            raise ValueError(f"{run_id} refers to an unmigrated source: {legacy_source_id}")
        artifact_url = _text(metadata.get("artifact_url"), f"{run_id} artifact_url")
        title = _text(metadata.get("title"), f"{run_id} title")
        published_at_text = _text(
            metadata.get("published_at"), f"{run_id} published_at"
        )
        published_at = _timestamp(published_at_text, f"{run_id} published_at")
        for name in _raw_names(run_dir):
            source_path = run_dir / name
            if not source_path.is_file():
                raise ValueError(f"missing raw run file: {source_path}")
            target = records / "raw" / run_id / name
            content = source_path.read_bytes()
            outputs.append(
                _Output(
                    target,
                    content,
                    "preserve_raw",
                    _relative(source_path, root),
                )
            )
        payload_path = run_dir / "payload.json"
        evidence_ids: list[str] = []
        artifact_content = (run_dir / "artifact.md").read_bytes()
        artifact_sha256 = _sha256(artifact_content)
        episode_id = episode_id_for(
            source_id, artifact_url, published_at, artifact_sha256
        )
        retrieved_at = published_at
        retrieval_basis = "source_published_at_fallback"
        retrieval_source = f"{_relative(metadata_path, root)}#/published_at"
        previous_episode: ResearchEpisode | None = None
        if payload_path.is_file():
            payload = _read_json(payload_path)
            created_at = payload.get("created_at")
            if isinstance(created_at, str) and created_at:
                retrieved_at = _timestamp(created_at, f"{run_id} created_at")
                retrieval_basis = "legacy_payload_created_at"
                retrieval_source = f"{_relative(payload_path, root)}#/created_at"
            for capture in _legacy_evidence(payload, payload_path, root):
                _merge_evidence(evidence_by_id, capture)
                evidence_ids.append(capture.evidence_id)
        elif previous_manifest is not None:
            previous_episode_path = records / "episodes" / f"{episode_id}.json"
            if not previous_episode_path.is_file():
                raise MigrationConflictError(
                    f"migrated episode record is missing: {previous_episode_path}"
                )
            previous_episode = ResearchEpisode.model_validate_json(
                previous_episode_path.read_text()
            )
            if (
                previous_episode.source_id != source_id
                or str(previous_episode.artifact_url) != artifact_url
                or previous_episode.title != title
                or previous_episode.published_at != published_at
                or previous_episode.content_sha256 != artifact_sha256
                or previous_episode.completeness != "unknown"
                or previous_episode.attribution_quality != "direct"
            ):
                raise MigrationConflictError(
                    f"migrated episode conflicts with raw inputs: {previous_episode_path}"
                )
            retrieved_at = previous_episode.retrieved_at
            retrieval_provenance = _object(
                previous_manifest.get("episode_retrieval_provenance"),
                "migration episode retrieval provenance",
            )
            retrieval_entry = _object(
                retrieval_provenance.get(episode_id),
                f"migration episode retrieval provenance {episode_id}",
            )
            retrieval_basis = _text(
                retrieval_entry.get("basis"),
                f"migration episode retrieval provenance {episode_id} basis",
            )
            retrieval_source = _text(
                retrieval_entry.get("source"),
                f"migration episode retrieval provenance {episode_id} source",
            )
            for capture in _previous_evidence_for_run(
                root, previous_manifest, run_id
            ):
                _merge_evidence(evidence_by_id, capture)
                evidence_ids.append(capture.evidence_id)
        supplement_urls = {
            _text(
                _object(value, f"{run_id} supplement").get("url"),
                f"{run_id} supplement url",
            )
            for value in _array(metadata.get("supplements", []), f"{run_id} supplements")
        }
        if previous_episode is None:
            supplement_evidence_ids = sorted(
                evidence_id
                for evidence_id in set(evidence_ids)
                if evidence_by_id[evidence_id].url in supplement_urls
            )
        else:
            supplement_evidence_ids = list(previous_episode.supplement_evidence_ids)
            if any(
                evidence_id not in evidence_by_id
                for evidence_id in supplement_evidence_ids
            ):
                raise MigrationConflictError(
                    f"migrated episode references missing evidence: {episode_id}"
                )
        episode_data: dict[str, JsonValue] = {
            "episode_id": episode_id,
            "source_id": source_id,
            "artifact_url": artifact_url,
            "title": title,
            "published_at": published_at.isoformat(),
            "retrieved_at": retrieved_at.isoformat(),
            "content_sha256": artifact_sha256,
            "completeness": "unknown",
            "attribution_quality": "direct",
            "supplement_evidence_ids": list(supplement_evidence_ids),
        }
        episode = ResearchEpisode.model_validate(episode_data)
        episode_retrieval_provenance.append(
            (episode_id, retrieval_basis, retrieval_source)
        )
        outputs.append(
            _Output(
                records / "episodes" / f"{episode_id}.json",
                _model_bytes(episode),
                "write_episode",
                _relative(metadata_path, root),
            )
        )
        for derived_name in ("payload.json", "technicals.json", "report.html"):
            derived_path = run_dir / derived_name
            derived_source = _relative(derived_path, root)
            recognized_discard_sources.add(derived_source)
            if derived_path.exists() and not derived_path.is_file():
                raise ValueError(f"derived migration target must be a file: {derived_path}")
            if derived_path.is_file():
                discards.append(derived_path)
            if derived_path.is_file() or derived_source in previous_discard_sources:
                actions.append(
                    MigrationAction(
                        "discard_derived",
                        derived_source,
                        None,
                        None,
                        "derived_or_contaminated_v1_state",
                    )
                )

    for evidence_id, capture in sorted(evidence_by_id.items()):
        record_data: dict[str, JsonValue] = {
            "evidence_id": evidence_id,
            "url": capture.url,
            "quote": capture.quote,
            "retrieved_at": capture.retrieved_at,
            "published_at": None,
            "content_sha256": _sha256(capture.quote.encode()),
            "capture_kind": "quote_only_legacy",
        }
        record = EvidenceCapture.model_validate(record_data)
        outputs.append(
            _Output(
                records / "evidence" / f"{evidence_id}.json",
                _model_bytes(record),
                "write_evidence",
                capture.origins[0],
            )
        )

    for derived_path in (
        root / "ledger" / "calls.csv",
        root / "ledger" / "source_scores.json",
    ):
        derived_source = _relative(derived_path, root)
        recognized_discard_sources.add(derived_source)
        if derived_path.exists() and not derived_path.is_file():
            raise ValueError(f"derived migration target must be a file: {derived_path}")
        if derived_path.is_file():
            discards.append(derived_path)
        if derived_path.is_file() or derived_source in previous_discard_sources:
            actions.append(
                MigrationAction(
                    "discard_derived",
                    derived_source,
                    None,
                    None,
                    "derived_or_contaminated_v1_state",
                )
            )
    unrecognized_discards = previous_discard_sources - recognized_discard_sources
    if unrecognized_discards:
        raise MigrationConflictError(
            "existing migration manifest contains unrecognized discard targets: "
            + ", ".join(sorted(unrecognized_discards))
        )
    return _Plan(
        source_ids=tuple(sorted(source_ids)),
        source_id_map=tuple(sorted(source_id_map.items())),
        outputs=tuple(outputs),
        discards=tuple(sorted(discards)),
        actions=tuple(actions),
        evidence_provenance=tuple(
            (evidence_id, capture.origins)
            for evidence_id, capture in sorted(evidence_by_id.items())
        ),
        episode_retrieval_provenance=tuple(sorted(episode_retrieval_provenance)),
        episode_count=len(run_dirs),
        evidence_count=len(evidence_by_id),
    )


def _write(
    path: Path, content: bytes, replace_existing: tuple[bytes, ...] = ()
) -> None:
    if path.exists():
        if not path.is_file():
            raise MigrationConflictError(f"migration target conflicts: {path}")
        existing = path.read_bytes()
        if existing == content:
            return
        if existing not in replace_existing:
            raise MigrationConflictError(f"migration target conflicts: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _verify_outputs(outputs: tuple[_Output, ...]) -> None:
    for output in outputs:
        if not output.path.is_file() or output.path.read_bytes() != output.content:
            raise MigrationConflictError(
                f"migration output failed verification: {output.path}"
            )


def _manifest_output(
    root: Path,
    common_body: dict[str, JsonValue],
    status: MigrationStatus,
    integrity_problems: tuple[str, ...],
) -> tuple[_Output, str]:
    body: dict[str, JsonValue] = dict(common_body)
    body["status"] = status
    body["integrity_problems"] = list(integrity_problems)
    manifest_sha256 = _sha256(_json_bytes(body))
    manifest: dict[str, JsonValue] = dict(body)
    manifest["manifest_sha256"] = manifest_sha256
    return (
        _Output(
            root / "records" / "migration-manifest.json",
            _json_bytes(manifest),
            "write_manifest",
            None,
        ),
        manifest_sha256,
    )


def migrate_v1(root: Path, dry_run: bool) -> MigrationResult:
    root = root.resolve()
    manifest_present = (root / "records" / "migration-manifest.json").is_file()
    try:
        _ensure_empty_v2_derived_state(root)
        plan = _planned_outputs(root)
        _ensure_unique_outputs(plan.outputs, root)
        _ensure_manifest_bound_records(root, plan.outputs, manifest_present)
    except MigrationConflictError:
        raise
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise MigrationConflictError(str(exc)) from exc
    output_actions = tuple(
        MigrationAction(
            output.kind,
            output.source,
            _relative(output.path, root),
            _sha256(output.content),
        )
        for output in plan.outputs
    )
    actions = tuple(
        sorted(
            output_actions + plan.actions,
            key=lambda action: (
                action.kind,
                action.source or "",
                action.target or "",
                action.sha256 or "",
                action.reason or "",
            ),
        )
    )
    raw_files: list[JsonValue] = []
    raw_files.extend(
        {
            "source": action.source,
            "target": action.target,
            "sha256": action.sha256,
        }
        for action in actions
        if action.kind == "preserve_raw"
    )
    source_id_map: dict[str, JsonValue] = {
        legacy_source_id: source_id
        for legacy_source_id, source_id in plan.source_id_map
    }
    evidence_provenance: dict[str, JsonValue] = {}
    for evidence_id, origins in plan.evidence_provenance:
        origin_values: list[JsonValue] = []
        origin_values.extend(origins)
        evidence_provenance[evidence_id] = origin_values
    episode_retrieval_provenance: dict[str, JsonValue] = {}
    for episode_id, basis, source in plan.episode_retrieval_provenance:
        episode_retrieval_provenance[episode_id] = {
            "basis": basis,
            "source": source,
        }
    manifest_body: dict[str, JsonValue] = {
        "schema_version": "2.0",
        "migration": "v1_to_v2_raw_only",
        "source_ids": list(plan.source_ids),
        "source_id_map": source_id_map,
        "episode_count": plan.episode_count,
        "evidence_count": plan.evidence_count,
        "raw_files": raw_files,
        "evidence_provenance": evidence_provenance,
        "episode_retrieval_provenance": episode_retrieval_provenance,
        "actions": [
            {
                "kind": action.kind,
                "source": action.source,
                "target": action.target,
                "sha256": action.sha256,
                "reason": action.reason,
            }
            for action in actions
        ],
    }
    final_manifest, manifest_sha256 = _manifest_output(
        root, manifest_body, "migration_complete", ()
    )
    partial_manifest, _ = _manifest_output(
        root,
        manifest_body,
        "migration_partial",
        ("derived v1 deletion pending",),
    )
    final_action = MigrationAction(
        "write_manifest",
        None,
        _relative(final_manifest.path, root),
        _sha256(final_manifest.content),
    )
    final_actions = actions + (final_action,)
    if not dry_run:
        for output in plan.outputs:
            if output.path.exists() and (
                not output.path.is_file() or output.path.read_bytes() != output.content
            ):
                raise MigrationConflictError(
                    f"migration target conflicts: {output.path}"
                )
        if final_manifest.path.exists():
            if not final_manifest.path.is_file():
                raise MigrationConflictError(
                    f"migration target conflicts: {final_manifest.path}"
                )
            existing_manifest = final_manifest.path.read_bytes()
            if existing_manifest not in (
                final_manifest.content,
                partial_manifest.content,
            ):
                raise MigrationConflictError(
                    f"migration target conflicts: {final_manifest.path}"
                )
            if plan.discards and existing_manifest == final_manifest.content:
                raise MigrationConflictError(
                    "derived v1 state appeared after migration completed"
                )
        for output in plan.outputs:
            _write(output.path, output.content)
        _verify_outputs(plan.outputs)
        (root / "records" / "research").mkdir(parents=True, exist_ok=True)
        (root / "records" / "candidates").mkdir(parents=True, exist_ok=True)
        if plan.discards:
            _write(partial_manifest.path, partial_manifest.content)
            _verify_outputs((partial_manifest,))
            for path in plan.discards:
                path.unlink(missing_ok=True)
            for path in plan.discards:
                if path.exists():
                    raise MigrationConflictError(
                        f"derived v1 target survived migration: {path}"
                    )
        _write(
            final_manifest.path,
            final_manifest.content,
            replace_existing=(partial_manifest.content,),
        )
        _verify_outputs((final_manifest,))
    return MigrationResult(
        status="migration_complete",
        source_ids=plan.source_ids,
        episode_count=plan.episode_count,
        evidence_count=plan.evidence_count,
        manifest_sha256=manifest_sha256,
        manifest_json=final_manifest.content.decode(),
        actions=final_actions,
    )


def fresh_start(root: Path, dry_run: bool) -> ResetResult:
    root = root.resolve()
    records = root / "records"
    if not records.is_dir():
        raise ValueError(f"v2 records directory not found: {records}")
    targets = tuple(
        sorted(
            {
                *records.joinpath("research").glob("*.json"),
                *records.joinpath("candidates").glob("*.json"),
                *records.joinpath("reports").glob("*.html"),
                *root.joinpath("reports").glob("*.html"),
            }
        )
    )
    removed = tuple(_relative(path, root) for path in targets if path.is_file())
    if not dry_run:
        for path in targets:
            if path.is_file():
                path.unlink()
    return ResetResult(removed=removed)
