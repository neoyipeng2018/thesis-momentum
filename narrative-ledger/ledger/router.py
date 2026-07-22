from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias

from .candidates import active_candidates
from .check import check_case
from .models import (
    CheckResult,
    EvidenceCapture,
    ResearchCase,
    ResearchEpisode,
    SourceProfile,
    ValidatedCandidate,
    research_episodes_by_id,
    source_profiles_by_id,
    source_is_currently_qualified,
)

RouterMode: TypeAlias = Literal["scout", "scan", "underwrite", "monitor", "full"]
RouterTerminal: TypeAlias = Literal[
    "awaiting_manual_qualification",
    "source_qualified",
    "source_rejected",
    "discovery_exhausted",
    "no_qualified_sources",
    "episodes_captured",
    "no_episodes_captured",
    "no_actionable_thesis",
    "source_not_qualified",
    "check_failed",
    "unscorable",
    "insufficient_material",
    "reject",
    "watch",
    "validated_trade_candidate",
    "no_active_candidates",
    "candidate_current",
    "research_refresh_required",
    "candidate_expired",
    "source_qualification_suspended",
    "monitoring_incomplete",
]


@dataclass(frozen=True)
class ModeResult:
    mode: RouterMode
    terminal_state: RouterTerminal
    source_ids: tuple[str, ...] = ()
    episode_ids: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()
    check_result: CheckResult | None = None


def scout(profiles: Collection[SourceProfile]) -> ModeResult:
    ordered = tuple(
        profile
        for _, profile in sorted(source_profiles_by_id(profiles).items())
    )
    source_ids = tuple(profile.source_id for profile in ordered)
    if not ordered:
        return ModeResult("scout", "discovery_exhausted")
    if any(profile.qualification_status == "probationary" for profile in ordered):
        return ModeResult("scout", "awaiting_manual_qualification", source_ids)
    if any(profile.qualification_status == "qualified" for profile in ordered):
        return ModeResult("scout", "source_qualified", source_ids)
    return ModeResult("scout", "source_rejected", source_ids)


def scan(
    profiles: Collection[SourceProfile],
    episodes: Collection[ResearchEpisode],
    start: datetime,
    end: datetime,
    as_of: datetime,
) -> ModeResult:
    if any(value.utcoffset() is None for value in (start, end, as_of)):
        raise ValueError("scan timestamps must be timezone-aware")
    if start > end or end > as_of:
        raise ValueError("scan window must end at or before as_of")
    profiles_by_id = source_profiles_by_id(profiles)
    episodes_by_id = research_episodes_by_id(episodes)
    qualified = tuple(
        sorted(
            (
                profile
                for profile in profiles_by_id.values()
                if source_is_currently_qualified(profile, as_of)
            ),
            key=lambda profile: profile.source_id,
        )
    )
    source_ids = tuple(profile.source_id for profile in qualified)
    if not qualified:
        return ModeResult("scan", "no_qualified_sources")
    allowed = frozenset(source_ids)
    captured = tuple(
        sorted(
            (
                episode
                for episode in episodes_by_id.values()
                if episode.source_id in allowed
                and start <= episode.published_at <= end
                and episode.retrieved_at <= as_of
            ),
            key=lambda episode: episode.episode_id,
        )
    )
    if not captured:
        return ModeResult("scan", "no_episodes_captured", source_ids)
    return ModeResult(
        "scan",
        "episodes_captured",
        source_ids,
        tuple(episode.episode_id for episode in captured),
    )


def underwrite(
    case: ResearchCase,
    profile: SourceProfile,
    episode: ResearchEpisode,
    evidence: Collection[EvidenceCapture],
) -> ModeResult:
    checked = check_case(case, profile, episode, evidence)
    issue_codes = frozenset(issue.code for issue in checked.issues)
    qualification_issues = {
        "source_not_qualified",
        "qualification_expired",
        "qualification_after_as_of",
        "qualification_evidence_after_assessment",
        "scope_not_qualified",
    }
    if issue_codes & qualification_issues:
        terminal: RouterTerminal = "source_not_qualified"
    elif checked.valid:
        terminal = checked.disposition
    else:
        terminal = "check_failed"
    return ModeResult(
        "underwrite",
        terminal,
        (profile.source_id,),
        (episode.episode_id,),
        check_result=checked,
    )


def monitor(
    candidates: Collection[ValidatedCandidate],
    profiles: Collection[SourceProfile],
    as_of: datetime,
) -> ModeResult:
    if as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if not candidates:
        return ModeResult("monitor", "no_active_candidates")
    current = active_candidates(candidates, profiles, as_of)
    if current:
        refresh_due = tuple(
            candidate
            for candidate in current
            if candidate.catalyst.by_date <= as_of.date()
            or any(
                invalidator.review_at <= as_of
                for invalidator in candidate.invalidators
            )
        )
        if refresh_due:
            return ModeResult(
                "monitor",
                "research_refresh_required",
                candidate_ids=tuple(
                    candidate.candidate_id for candidate in refresh_due
                ),
            )
        return ModeResult(
            "monitor",
            "candidate_current",
            candidate_ids=tuple(candidate.candidate_id for candidate in current),
        )
    profiles_by_id = source_profiles_by_id(profiles)
    if any(
        candidate.source_id not in profiles_by_id
        or not source_is_currently_qualified(
            profiles_by_id[candidate.source_id], as_of, candidate.scope
        )
        for candidate in candidates
    ):
        terminal: RouterTerminal = "source_qualification_suspended"
    elif all(candidate.valid_until <= as_of for candidate in candidates):
        terminal = "candidate_expired"
    else:
        terminal = "monitoring_incomplete"
    return ModeResult("monitor", terminal)


def full(
    profiles: Collection[SourceProfile],
    episodes: Collection[ResearchEpisode],
    case: ResearchCase,
    evidence: Collection[EvidenceCapture],
    start: datetime,
    end: datetime,
    as_of: datetime,
) -> ModeResult:
    if case.as_of != as_of:
        raise ValueError("case as_of must equal full as_of")
    profile_by_id = source_profiles_by_id(profiles)
    target_profile = profile_by_id.get(case.source_id)
    if target_profile is None:
        return ModeResult("full", "source_not_qualified")
    scouted = scout((target_profile,))
    if scouted.terminal_state != "source_qualified":
        return ModeResult(
            "full",
            scouted.terminal_state,
            scouted.source_ids,
        )
    scanned = scan(profiles, episodes, start, end, as_of)
    if scanned.terminal_state != "episodes_captured":
        return ModeResult(
            "full",
            scanned.terminal_state,
            scanned.source_ids,
            scanned.episode_ids,
        )
    episode_by_id = research_episodes_by_id(episodes)
    if case.episode_id not in scanned.episode_ids:
        return ModeResult(
            "full",
            "no_actionable_thesis",
            scanned.source_ids,
            scanned.episode_ids,
        )
    result = underwrite(
        case,
        profile_by_id[case.source_id],
        episode_by_id[case.episode_id],
        evidence,
    )
    return ModeResult(
        "full",
        result.terminal_state,
        result.source_ids,
        result.episode_ids,
        result.candidate_ids,
        result.check_result,
    )
