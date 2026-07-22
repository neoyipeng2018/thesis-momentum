from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .models import (
    Assertion,
    DateHorizon,
    EvidenceCapture,
    EventHorizon,
    Horizon,
    MonitoringTrigger,
    SessionHorizon,
    SourceProfile,
    ValidatedCandidate,
    contains_portfolio_instruction,
)


TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"


@dataclass(frozen=True)
class TriggerViewModel:
    due_at: str
    condition: str
    kind: str


@dataclass(frozen=True)
class AssertionViewModel:
    text: str
    provenance: str
    verdict: str
    evidence_count: int


@dataclass(frozen=True)
class EvidenceViewModel:
    label: str
    retrieved_at: str
    url: str
    quote: str
    capture_quality: str


@dataclass(frozen=True)
class CandidateViewModel:
    headline: str
    thesis: str
    source_name: str
    scope: str
    qualification_status: str
    published_at: str
    valid_until: str
    instrument: str
    direction: str
    horizon: str
    expression_origin: str
    expression_origin_note: str
    expectations_gap: str
    catalyst: str
    downside: str
    countercase: str
    invalidators: tuple[TriggerViewModel, ...]
    assertions: tuple[AssertionViewModel, ...]
    evidence: tuple[EvidenceViewModel, ...]
    candidate_id: str
    case_id: str
    episode_id: str
    check_digest: str
    evaluator_version: str


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _format_horizon(horizon: Horizon) -> str:
    if isinstance(horizon, SessionHorizon):
        suffix = "session" if horizon.sessions == 1 else "sessions"
        return f"{horizon.sessions} {suffix}"
    if isinstance(horizon, DateHorizon):
        return f"through {horizon.by_date.isoformat()}"
    if isinstance(horizon, EventHorizon):
        return f"{horizon.event} by {horizon.by_date.isoformat()}"
    raise TypeError(f"unsupported horizon: {type(horizon).__name__}")


def _operator_text(trigger: MonitoringTrigger) -> str:
    operators = {
        "lt": "<",
        "lte": "≤",
        "gt": ">",
        "gte": "≥",
        "eq": "=",
        "published": "published",
        "not_published": "not published",
        "changes": "changes to",
    }
    return operators[trigger.operator]


def _trigger_view(trigger: MonitoringTrigger) -> TriggerViewModel:
    condition = (
        f"{trigger.description} "
        f"({trigger.metric} {_operator_text(trigger)} {trigger.target_value})"
    )
    return TriggerViewModel(
        due_at=_format_timestamp(trigger.review_at),
        condition=condition,
        kind="invalidation",
    )


def _assertion_view(assertion: Assertion) -> AssertionViewModel:
    return AssertionViewModel(
        text=assertion.statement,
        provenance=assertion.provenance,
        verdict=assertion.verdict,
        evidence_count=len(set(assertion.evidence_ids)),
    )


def _evidence_views(
    candidate: ValidatedCandidate,
    evidence: Collection[EvidenceCapture],
) -> tuple[EvidenceViewModel, ...]:
    captures_by_id = {capture.evidence_id: capture for capture in evidence}
    requested_ids = tuple(sorted(set(candidate.evidence_ids)))
    missing_ids = tuple(
        evidence_id for evidence_id in requested_ids if evidence_id not in captures_by_id
    )
    if missing_ids:
        raise ValueError(f"candidate evidence is unavailable: {', '.join(missing_ids)}")
    instruction_ids = tuple(
        evidence_id
        for evidence_id in requested_ids
        if contains_portfolio_instruction(captures_by_id[evidence_id].quote)
    )
    if instruction_ids:
        raise ValueError(
            "candidate evidence contains portfolio instructions: "
            + ", ".join(instruction_ids)
        )
    return tuple(
        EvidenceViewModel(
            label=f"{captures_by_id[evidence_id].capture_kind} · {evidence_id}",
            retrieved_at=_format_timestamp(captures_by_id[evidence_id].retrieved_at),
            url=str(captures_by_id[evidence_id].url),
            quote=captures_by_id[evidence_id].quote,
            capture_quality=captures_by_id[evidence_id].capture_kind,
        )
        for evidence_id in requested_ids
    )


def _candidate_view(
    candidate: ValidatedCandidate,
    profile: SourceProfile,
    evidence: Collection[EvidenceCapture],
) -> CandidateViewModel:
    if candidate.source_id != profile.source_id:
        raise ValueError("candidate and source profile identify different sources")
    if profile.qualification_status != "qualified":
        raise ValueError("candidate report requires a qualified source profile")
    if candidate.scope not in profile.declared_scopes:
        raise ValueError("candidate report scope is no longer qualified")
    expression = candidate.expression
    origin_note = (
        f"instrument {expression.instrument_provenance} · "
        f"direction {expression.direction_provenance} · "
        f"horizon {expression.horizon_provenance}"
    )
    catalyst = (
        f"{candidate.catalyst.description} Due {candidate.catalyst.by_date.isoformat()}. "
        f"Provenance: {candidate.catalyst.provenance}."
    )
    return CandidateViewModel(
        headline=(
            f"{expression.direction.upper()} {expression.instrument} — "
            "validated research candidate"
        ),
        thesis=candidate.thesis,
        source_name=profile.name,
        scope=candidate.scope,
        qualification_status=profile.qualification_status,
        published_at=_format_timestamp(candidate.published_at),
        valid_until=_format_timestamp(candidate.valid_until),
        instrument=expression.instrument,
        direction=expression.direction,
        horizon=_format_horizon(expression.horizon),
        expression_origin=expression.origin,
        expression_origin_note=origin_note,
        expectations_gap=candidate.expectations_gap,
        catalyst=catalyst,
        downside=candidate.downside,
        countercase=candidate.countercase,
        invalidators=tuple(_trigger_view(item) for item in candidate.invalidators),
        assertions=tuple(_assertion_view(item) for item in candidate.assertions),
        evidence=_evidence_views(candidate, evidence),
        candidate_id=candidate.candidate_id,
        case_id=candidate.case_id,
        episode_id=candidate.episode_id,
        check_digest=candidate.check_digest,
        evaluator_version=candidate.checker_version,
    )


def render_candidate(
    candidate: ValidatedCandidate,
    profile: SourceProfile,
    evidence: Collection[EvidenceCapture],
    output: str | Path,
) -> None:
    if not isinstance(candidate, ValidatedCandidate):
        raise TypeError("render_candidate requires a ValidatedCandidate")
    view = _candidate_view(candidate, profile, evidence)
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_ROOT),
        autoescape=True,
        undefined=StrictUndefined,
    )
    html = environment.get_template("candidate.html.j2").render(
        candidate=view,
        generated_at=_format_timestamp(datetime.now(timezone.utc)),
    )
    Path(output).write_text(html, encoding="utf-8")
