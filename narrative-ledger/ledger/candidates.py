from __future__ import annotations

import os
import tempfile
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .check import check_case
from .models import (
    DateHorizon,
    EvidenceCapture,
    EventHorizon,
    ResearchCase,
    ResearchEpisode,
    SourceProfile,
    ValidatedCandidate,
    candidate_id_for,
    referenced_evidence_ids,
    source_profiles_by_id,
    source_is_currently_qualified,
)
from .storage import load_model


class CandidatePublicationError(RuntimeError):
    pass


class StaleCheckError(CandidatePublicationError):
    pass


class CandidateConflictError(CandidatePublicationError):
    pass


@dataclass(frozen=True)
class PublicationResult:
    candidate: ValidatedCandidate
    path: Path
    created: bool


def _candidate(
    case: ResearchCase,
    profile: SourceProfile,
    episode: ResearchEpisode,
    check_digest: str,
    checker_version: str,
    published_at: datetime,
) -> ValidatedCandidate:
    if (
        case.thesis is None
        or case.expectations_gap is None
        or case.downside is None
        or case.countercase is None
        or case.expression is None
        or case.catalyst is None
        or case.valid_until is None
    ):
        raise CandidatePublicationError("checked candidate is missing required fields")
    if published_at.utcoffset() is None:
        raise CandidatePublicationError("candidate publication time must be timezone-aware")
    if published_at < case.as_of:
        raise CandidatePublicationError(
            "candidate publication cannot precede the case as-of time"
        )
    if not source_is_currently_qualified(profile, published_at, case.scope):
        raise CandidatePublicationError(
            "source qualification is not current at candidate publication"
        )
    if case.catalyst.by_date <= published_at.date() or any(
        invalidator.review_at <= published_at for invalidator in case.invalidators
    ):
        raise CandidatePublicationError(
            "candidate research is due for refresh at publication"
        )
    if isinstance(case.expression.horizon, DateHorizon | EventHorizon) and (
        case.expression.horizon.by_date <= published_at.date()
    ):
        raise CandidatePublicationError(
            "candidate expression horizon is stale at publication"
        )
    return ValidatedCandidate(
        candidate_id=candidate_id_for(check_digest),
        case_id=case.case_id,
        source_id=case.source_id,
        scope=case.scope,
        episode_id=case.episode_id,
        check_digest=check_digest,
        checker_version=checker_version,
        published_at=published_at,
        valid_until=case.valid_until,
        thesis=case.thesis,
        expectations_gap=case.expectations_gap,
        downside=case.downside,
        assertions=case.assertions,
        countercase=case.countercase,
        expression=case.expression,
        catalyst=case.catalyst,
        invalidators=case.invalidators,
        evidence_ids=referenced_evidence_ids(case, profile, episode),
    )


def _load_bound_candidate(
    path: Path,
    case: ResearchCase,
    profile: SourceProfile,
    episode: ResearchEpisode,
    check_digest: str,
    checker_version: str,
) -> ValidatedCandidate:
    existing = load_model(path, ValidatedCandidate)
    try:
        expected = _candidate(
            case,
            profile,
            episode,
            check_digest,
            checker_version,
            existing.published_at,
        )
    except CandidatePublicationError as error:
        raise CandidateConflictError(
            f"candidate record is not bound to checked inputs: {path}"
        ) from error
    if existing != expected:
        raise CandidateConflictError(
            f"candidate record is not bound to checked inputs: {path}"
        )
    return existing


def _write_exclusive(path: Path, candidate: ValidatedCandidate) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"{candidate.model_dump_json(indent=2)}\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            return False
        return True
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def publish_candidate(
    case: ResearchCase,
    profile: SourceProfile,
    episode: ResearchEpisode,
    evidence: Collection[EvidenceCapture],
    expected_digest: str,
    published_at: datetime,
    candidate_directory: Path,
) -> PublicationResult:
    checked = check_case(case, profile, episode, evidence)
    if checked.digest != expected_digest:
        raise StaleCheckError("checked inputs changed; run check again")
    if not checked.publishable:
        issue_codes = ", ".join(issue.code for issue in checked.issues)
        raise CandidatePublicationError(
            f"research case is not publishable: {issue_codes or checked.disposition}"
        )
    candidate_id = candidate_id_for(checked.digest)
    path = candidate_directory / f"{candidate_id}.json"
    if path.exists():
        existing = _load_bound_candidate(
            path,
            case,
            profile,
            episode,
            checked.digest,
            checked.checker_version,
        )
        return PublicationResult(existing, path, False)
    candidate = _candidate(
        case,
        profile,
        episode,
        checked.digest,
        checked.checker_version,
        published_at,
    )
    created = _write_exclusive(path, candidate)
    if created:
        return PublicationResult(candidate, path, True)
    existing = _load_bound_candidate(
        path,
        case,
        profile,
        episode,
        checked.digest,
        checked.checker_version,
    )
    return PublicationResult(existing, path, False)


def list_candidates(candidate_directory: Path) -> tuple[ValidatedCandidate, ...]:
    if not candidate_directory.is_dir():
        return ()
    return tuple(
        load_model(path, ValidatedCandidate)
        for path in sorted(candidate_directory.glob("*.json"))
    )


def active_candidates(
    candidates: Collection[ValidatedCandidate],
    profiles: Collection[SourceProfile],
    as_of: datetime,
) -> tuple[ValidatedCandidate, ...]:
    if as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    profiles_by_id = source_profiles_by_id(profiles)
    active: list[ValidatedCandidate] = []
    for candidate in candidates:
        profile = profiles_by_id.get(candidate.source_id)
        if profile is None or not source_is_currently_qualified(
            profile, as_of, candidate.scope
        ):
            continue
        if candidate.published_at <= as_of < candidate.valid_until:
            active.append(candidate)
    return tuple(sorted(active, key=lambda candidate: candidate.candidate_id))
