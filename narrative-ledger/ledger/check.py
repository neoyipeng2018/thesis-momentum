from __future__ import annotations

import hashlib
from collections.abc import Collection

from .models import (
    CheckIssue,
    CheckIssueCode,
    CheckResult,
    DateHorizon,
    EvidenceCapture,
    EventHorizon,
    ResearchCase,
    ResearchEpisode,
    SourceProfile,
    candidate_instruction_text,
    contains_portfolio_instruction,
    referenced_evidence_ids,
    source_is_currently_qualified,
)

CHECKER_VERSION = "2.0.0"


def _content_digest(
    case: ResearchCase,
    profile: SourceProfile,
    episode: ResearchEpisode,
    captures: tuple[EvidenceCapture, ...],
) -> str:
    material = "\n".join(
        (
            CHECKER_VERSION,
            profile.model_dump_json(),
            episode.model_dump_json(),
            case.model_dump_json(),
            *(capture.model_dump_json() for capture in captures),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _issue(code: CheckIssueCode, path: str, message: str) -> CheckIssue:
    return CheckIssue(code=code, path=path, message=message)


def check_case(
    case: ResearchCase,
    profile: SourceProfile,
    episode: ResearchEpisode,
    evidence: Collection[EvidenceCapture],
) -> CheckResult:
    referenced_ids = frozenset(referenced_evidence_ids(case, profile, episode))
    capture_variants: dict[str, dict[str, EvidenceCapture]] = {}
    for capture in evidence:
        if capture.evidence_id not in referenced_ids:
            continue
        variants = capture_variants.setdefault(capture.evidence_id, {})
        variants[capture.model_dump_json()] = capture
    captures_by_id = {
        evidence_id: variants[min(variants)]
        for evidence_id, variants in capture_variants.items()
    }
    captures = tuple(
        capture_variants[evidence_id][serialised]
        for evidence_id in sorted(capture_variants)
        for serialised in sorted(capture_variants[evidence_id])
    )
    issues: list[CheckIssue] = []

    for evidence_id in sorted(capture_variants):
        if len(capture_variants[evidence_id]) > 1:
            issues.append(
                _issue(
                    "conflicting_evidence_capture",
                    f"evidence.{evidence_id}",
                    "one evidence ID resolves to conflicting capture metadata",
                )
            )

    if case.source_id != profile.source_id:
        issues.append(
            _issue(
                "profile_source_mismatch",
                "source_id",
                "research case and source profile identify different sources",
            )
        )
    if case.episode_id != episode.episode_id:
        issues.append(
            _issue(
                "case_episode_mismatch",
                "episode_id",
                "research case and episode identify different episodes",
            )
        )
    if case.source_id != episode.source_id or episode.source_id != profile.source_id:
        issues.append(
            _issue(
                "episode_source_mismatch",
                "episode.source_id",
                "research episode does not belong to the checked source",
            )
        )
    if (
        case.disposition == "validated_trade_candidate"
        and episode.retrieved_at > case.as_of
    ):
        issues.append(
            _issue(
                "episode_after_as_of",
                "episode.retrieved_at",
                "episode was retrieved after the candidate case as-of time",
            )
        )
    if (
        case.disposition == "validated_trade_candidate"
        and episode.completeness != "full"
    ):
        issues.append(
            _issue(
                "episode_incomplete",
                "episode.completeness",
                "candidate requires a complete source artifact",
            )
        )
    if (
        case.disposition == "validated_trade_candidate"
        and episode.attribution_quality == "reconstructed"
    ):
        issues.append(
            _issue(
                "episode_attribution_reconstructed",
                "episode.attribution_quality",
                "candidate cannot rely on reconstructed source attribution",
            )
        )
    if not source_is_currently_qualified(profile, case.as_of, case.scope):
        if profile.qualification_status != "qualified":
            issues.append(
                _issue(
                    "source_not_qualified",
                    "profile.qualification_status",
                    "source must be qualified before underwriting can pass check",
                )
            )
        if case.scope not in profile.declared_scopes:
            issues.append(
                _issue(
                    "scope_not_qualified",
                    "scope",
                    "research case is outside the source's qualified scope",
                )
            )
        if profile.review_due_at is not None and case.as_of > profile.review_due_at:
            issues.append(
                _issue(
                    "qualification_expired",
                    "profile.review_due_at",
                    "source qualification is expired at the case as-of time",
                )
            )
        if profile.assessed_at is not None and profile.assessed_at > case.as_of:
            issues.append(
                _issue(
                    "qualification_after_as_of",
                    "profile.assessed_at",
                    "source qualification was assessed after the case as-of time",
                )
            )

    available_ids = frozenset(captures_by_id)
    for evidence_id in sorted(referenced_ids):
        if evidence_id not in available_ids:
            issues.append(
                _issue(
                    "missing_evidence",
                    "evidence",
                    f"referenced evidence is unavailable: {evidence_id}",
                )
            )
        elif (
            case.disposition == "validated_trade_candidate"
            and captures_by_id[evidence_id].retrieved_at > case.as_of
        ):
            issues.append(
                _issue(
                    "evidence_after_as_of",
                    "evidence",
                    f"evidence was captured after the case as-of time: {evidence_id}",
                )
            )

    for evidence_id in profile.qualification_evidence_ids:
        qualification_capture = captures_by_id.get(evidence_id)
        if (
            qualification_capture is not None
            and qualification_capture.capture_kind == "quote_only_legacy"
        ):
            issues.append(
                _issue(
                    "legacy_evidence",
                    "profile.qualification_evidence_ids",
                    "qualification cannot rely on legacy quote-only evidence",
                )
            )
        if (
            qualification_capture is not None
            and profile.assessed_at is not None
            and qualification_capture.retrieved_at > profile.assessed_at
        ):
            issues.append(
                _issue(
                    "qualification_evidence_after_assessment",
                    "profile.qualification_evidence_ids",
                    "qualification evidence must exist by the assessment time",
                )
            )

    if case.disposition == "watch":
        if case.watch_trigger is None:
            issues.append(
                _issue(
                    "watch_trigger_required",
                    "watch_trigger",
                    "watch disposition requires a dated measurable trigger",
                )
            )
        elif case.watch_trigger.review_at <= case.as_of:
            issues.append(
                _issue(
                    "invalid_watch_trigger",
                    "watch_trigger.review_at",
                    "watch trigger review must be after the case as-of time",
                )
            )

    if case.disposition == "validated_trade_candidate":
        _check_candidate(case, captures_by_id, issues)

    valid = not issues
    return CheckResult(
        checker_version=CHECKER_VERSION,
        case_id=case.case_id,
        disposition=case.disposition,
        digest=_content_digest(case, profile, episode, captures),
        valid=valid,
        publishable=valid and case.disposition == "validated_trade_candidate",
        issues=tuple(issues),
    )


def _check_candidate(
    case: ResearchCase,
    captures_by_id: dict[str, EvidenceCapture],
    issues: list[CheckIssue],
) -> None:
    required_text: tuple[tuple[str | None, CheckIssueCode, str, str], ...] = (
        (case.thesis, "thesis_required", "thesis", "candidate requires a thesis"),
        (
            case.expectations_gap,
            "expectations_gap_required",
            "expectations_gap",
            "candidate requires an explicit expectations gap",
        ),
        (
            case.downside,
            "downside_required",
            "downside",
            "candidate requires an explicit downside",
        ),
        (
            case.countercase,
            "countercase_required",
            "countercase",
            "candidate requires a countercase",
        ),
    )
    for value, code, path, message in required_text:
        if value is None:
            issues.append(_issue(code, path, message))

    for path, value in candidate_instruction_text(case):
        if contains_portfolio_instruction(value):
            issues.append(
                _issue(
                    "portfolio_instruction_language",
                    path,
                    "candidate research text contains portfolio instructions",
                )
            )
    for evidence_id, instruction_capture in sorted(captures_by_id.items()):
        if contains_portfolio_instruction(instruction_capture.quote):
            issues.append(
                _issue(
                    "portfolio_instruction_language",
                    f"evidence.{evidence_id}.quote",
                    "candidate evidence contains portfolio instructions",
                )
            )

    if case.expression is None:
        issues.append(
            _issue(
                "expression_required",
                "expression",
                "candidate requires a source or researcher expression",
            )
        )
    else:
        expression_provenance = (
            ("instrument_provenance", case.expression.instrument_provenance),
            ("direction_provenance", case.expression.direction_provenance),
            ("horizon_provenance", case.expression.horizon_provenance),
        )
        for field_name, provenance in expression_provenance:
            if provenance == "missing":
                issues.append(
                    _issue(
                        "missing_provenance",
                        f"expression.{field_name}",
                        "candidate expression dimensions require known provenance",
                    )
                )
        horizon = case.expression.horizon
        if isinstance(horizon, DateHorizon | EventHorizon):
            if horizon.by_date <= case.as_of.date():
                issues.append(
                    _issue(
                        "invalid_expression_horizon",
                        "expression.horizon.by_date",
                        "dated expression horizon must be in the future",
                    )
                )
            elif (
                case.valid_until is not None
                and horizon.by_date > case.valid_until.date()
            ):
                issues.append(
                    _issue(
                        "invalid_expression_horizon",
                        "expression.horizon.by_date",
                        "dated expression horizon cannot exceed candidate validity",
                    )
                )
    if case.catalyst is None:
        issues.append(
            _issue("catalyst_required", "catalyst", "candidate requires a catalyst")
        )
    else:
        if case.catalyst.provenance == "missing":
            issues.append(
                _issue(
                    "missing_provenance",
                    "catalyst.provenance",
                    "candidate catalyst requires known provenance",
                )
            )
        if not case.catalyst.evidence_ids:
            issues.append(
                _issue(
                    "catalyst_evidence_required",
                    "catalyst.evidence_ids",
                    "candidate catalyst requires evidence",
                )
            )
        if case.catalyst.by_date <= case.as_of.date():
            issues.append(
                _issue(
                    "catalyst_due",
                    "catalyst.by_date",
                    "candidate catalyst must be in the future at the case as-of time",
                )
            )
    if not case.invalidators:
        issues.append(
            _issue(
                "invalidator_required",
                "invalidators",
                "candidate requires at least one monitorable invalidator",
            )
        )
    if case.valid_until is None:
        issues.append(
            _issue(
                "valid_until_required",
                "valid_until",
                "candidate requires a validity window",
            )
        )
    elif case.valid_until <= case.as_of:
        issues.append(
            _issue(
                "invalid_validity_window",
                "valid_until",
                "candidate validity must extend beyond the case as-of time",
            )
        )

    load_bearing = tuple(
        assertion for assertion in case.assertions if assertion.load_bearing
    )
    if not load_bearing:
        issues.append(
            _issue(
                "load_bearing_assertion_required",
                "assertions",
                "candidate requires at least one load-bearing assertion",
            )
        )
    for assertion in load_bearing:
        if assertion.provenance == "missing":
            issues.append(
                _issue(
                    "missing_provenance",
                    f"assertions.{assertion.assertion_id}.provenance",
                    "load-bearing assertion requires known provenance",
                )
            )
        if assertion.verdict != "supports":
            issues.append(
                _issue(
                    "load_bearing_assertion_not_supported",
                    f"assertions.{assertion.assertion_id}.verdict",
                    "every load-bearing assertion must be supported",
                )
            )
        for evidence_id in assertion.evidence_ids:
            capture = captures_by_id.get(evidence_id)
            if capture is not None and capture.capture_kind == "quote_only_legacy":
                issues.append(
                    _issue(
                        "legacy_evidence",
                        f"assertions.{assertion.assertion_id}.evidence_ids",
                        "load-bearing assertions cannot rely on legacy quote-only evidence",
                    )
                )
        if not any(
            captures_by_id[evidence_id].capture_kind == "primary"
            for evidence_id in assertion.evidence_ids
            if evidence_id in captures_by_id
        ):
            issues.append(
                _issue(
                    "primary_evidence_required",
                    f"assertions.{assertion.assertion_id}.evidence_ids",
                    "load-bearing assertion requires at least one primary evidence capture",
                )
            )

    if case.catalyst is not None:
        for evidence_id in case.catalyst.evidence_ids:
            capture = captures_by_id.get(evidence_id)
            if capture is not None and capture.capture_kind == "quote_only_legacy":
                issues.append(
                    _issue(
                        "legacy_evidence",
                        "catalyst.evidence_ids",
                        "candidate catalyst cannot rely on legacy quote-only evidence",
                    )
                )

    for index, invalidator in enumerate(case.invalidators):
        if invalidator.review_at <= case.as_of:
            issues.append(
                _issue(
                    "invalid_validity_window",
                    f"invalidators.{index}.review_at",
                    "invalidator review must be after the case as-of time",
                )
            )
