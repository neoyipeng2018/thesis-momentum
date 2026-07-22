from __future__ import annotations

import hashlib
import re
from collections.abc import Collection
from datetime import date, datetime, timezone
from typing import Annotated, Literal, TypeAlias
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

QualificationStatus: TypeAlias = Literal[
    "probationary", "qualified", "suspended", "rejected"
]
Provenance: TypeAlias = Literal["stated", "inferred", "assumed", "missing"]
Disposition: TypeAlias = Literal[
    "unscorable",
    "no_actionable_thesis",
    "insufficient_material",
    "reject",
    "watch",
    "validated_trade_candidate",
]
EvidenceVerdict: TypeAlias = Literal[
    "supports", "refutes", "insufficient", "unverified"
]
EvidenceKind: TypeAlias = Literal["primary", "secondary", "quote_only_legacy"]
MaterialCompleteness: TypeAlias = Literal["full", "preview", "unknown"]
AttributionQuality: TypeAlias = Literal[
    "direct", "author_interview", "quoted_secondary", "reconstructed"
]
ExpressionOrigin: TypeAlias = Literal["source", "researcher"]
Direction: TypeAlias = Literal["long", "short"]
TriggerOperator: TypeAlias = Literal[
    "lt", "lte", "gt", "gte", "eq", "published", "not_published", "changes"
]
CheckIssueCode: TypeAlias = Literal[
    "profile_source_mismatch",
    "case_episode_mismatch",
    "episode_source_mismatch",
    "source_not_qualified",
    "qualification_expired",
    "qualification_after_as_of",
    "qualification_evidence_after_assessment",
    "scope_not_qualified",
    "missing_evidence",
    "legacy_evidence",
    "evidence_after_as_of",
    "conflicting_evidence_capture",
    "episode_after_as_of",
    "episode_incomplete",
    "episode_attribution_reconstructed",
    "primary_evidence_required",
    "missing_provenance",
    "load_bearing_assertion_required",
    "load_bearing_assertion_not_supported",
    "thesis_required",
    "expectations_gap_required",
    "downside_required",
    "countercase_required",
    "expression_required",
    "invalid_expression_horizon",
    "catalyst_required",
    "catalyst_evidence_required",
    "catalyst_due",
    "invalidator_required",
    "valid_until_required",
    "invalid_validity_window",
    "watch_trigger_required",
    "invalid_watch_trigger",
    "portfolio_instruction_language",
]

NonEmptyText: TypeAlias = Annotated[str, Field(min_length=1)]
Sha256: TypeAlias = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

_PORTFOLIO_INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:allocate|deploy|commit)\s+(?:up\s+to\s+)?\d+(?:\.\d+)?\s*%",
        r"\b(?:execute|place|submit)\s+(?:an?\s+)?(?:order|trade)\b",
        r"\b(?:starter|initial|target|maximum|max)\s+(?:position|allocation|size)\b",
        r"\b(?:size|weight)\s+(?:the\s+)?(?:position|trade|portfolio)\b",
        r"\b(?:buy|sell|short|cover|hold|increase|reduce|trim|exit|enter|open|close)\s+(?:the\s+)?(?:position|allocation|shares?)\b",
        r"\b(?:stop[- ]loss|limit order|market order|conviction[- ]sizing)\b",
        r"\b(?:buy|sell|short|cover)\s+\d+(?:\.\d+)?\s+(?:shares?|units?|contracts?)\b",
        r"\b(?:allocate|deploy|commit)\b.{0,48}\b(?:portfolio|capital|assets?|position)\b",
        r"\b(?:enter|exit)\s+\S+\s+at\s+\$?\d",
        r"\bset\b.{0,24}\b(?:stop|stop-loss)\b",
        r"\b(?:take|open|build|initiate|establish|add|trim|reduce|increase)\b.{0,40}\bposition\b",
        r"\b(?:position size|portfolio weight|target weight|risk budget|notional)\b",
        r"(?:^|[.!?]\s+|\n\s*)(?:please\s+)?(?:buy|sell|short|cover|hold|allocate|deploy|commit|enter|exit|place|submit|execute|set|take|open|close|build|initiate|establish|add|trim|reduce|increase|rotate|rebalance)\b",
        r"\b(?:place|submit)\s+(?:an?\s+)?(?:buy|sell|limit|market)?\s*order\b",
        r"\ballocate\s+\$\s*\d",
        r"\b(?:should|must|would)\s+(?:buy|sell|short|cover|hold|allocate|enter|exit|open|close|rotate|rebalance|stay\s+(?:long|short)|hang\s+on(?:to)?)\b",
        r"\b(?:do\s+not|don't|never)\s+(?:buy|sell|short|cover|hold|enter|exit|open|close|trim|reduce|increase)\b",
        r"\bstay\s+(?:long|short)\b",
        r"\bhang\s+on(?:to)?\b.{0,40}\b(?:names?|shares?|stocks?|equities?|positions?|holdings?|securities|contracts?|units?)\b",
        r"\b(?:rotate|rebalance)\s+(?:out\s+of|into|toward(?:s)?)\b",
    )
)


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _timestamp_text(value: datetime) -> str:
    _require_aware(value, "timestamp")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _require_sha256(value: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("content digest must be 64 lowercase hexadecimal characters")


def contains_portfolio_instruction(value: str) -> bool:
    return any(pattern.search(value) is not None for pattern in _PORTFOLIO_INSTRUCTION_PATTERNS)


def _normalise_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    path = parsed.path.rstrip("/")
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, parsed.fragment)
    )


def _stable_id(prefix: str, *parts: str) -> str:
    material = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(material).hexdigest()[:24]}"


def source_id_for(venue: str) -> str:
    return _stable_id("src", _normalise_url(venue))


def episode_id_for(
    source_id: str,
    artifact_url: str,
    published_at: datetime,
    content_sha256: str,
) -> str:
    _require_sha256(content_sha256)
    return _stable_id(
        "ep",
        source_id,
        _normalise_url(artifact_url),
        _timestamp_text(published_at),
        content_sha256,
    )


def evidence_id_for(
    url: str,
    quote: str,
    retrieved_at: datetime,
    content_sha256: str,
) -> str:
    _require_sha256(content_sha256)
    return _stable_id(
        "ev",
        _normalise_url(url),
        quote.strip(),
        _timestamp_text(retrieved_at),
        content_sha256,
    )


def case_id_for(source_id: str, episode_id: str, opened_at: datetime) -> str:
    return _stable_id("case", source_id, episode_id, _timestamp_text(opened_at))


def candidate_id_for(check_digest: str) -> str:
    _require_sha256(check_digest)
    return _stable_id("cand", check_digest)


class SourceProfile(Record):
    schema_version: Literal["2.0"] = "2.0"
    source_id: NonEmptyText
    name: NonEmptyText
    venue: HttpUrl
    feeds: tuple[HttpUrl, ...] = ()
    domains: tuple[NonEmptyText, ...]
    declared_scopes: tuple[NonEmptyText, ...] = ()
    qualification_status: QualificationStatus = "probationary"
    qualification_evidence_ids: tuple[NonEmptyText, ...] = ()
    assessor: NonEmptyText | None = None
    assessment_method: NonEmptyText | None = None
    assessed_at: datetime | None = None
    review_due_at: datetime | None = None

    @model_validator(mode="after")
    def validate_profile(self) -> SourceProfile:
        if self.source_id != source_id_for(str(self.venue)):
            raise ValueError("source_id does not match venue")
        if self.assessed_at is not None:
            _require_aware(self.assessed_at, "assessed_at")
        if self.review_due_at is not None:
            _require_aware(self.review_due_at, "review_due_at")
        if self.qualification_status == "qualified":
            required = (
                bool(self.declared_scopes),
                bool(self.qualification_evidence_ids),
                self.assessor is not None,
                self.assessment_method is not None,
                self.assessed_at is not None,
                self.review_due_at is not None,
            )
            if not all(required):
                raise ValueError(
                    "qualified source requires scope, evidence, assessor, method, "
                    "assessment time, and review date"
                )
        if (
            self.assessed_at is not None
            and self.review_due_at is not None
            and self.review_due_at <= self.assessed_at
        ):
            raise ValueError("review_due_at must be after assessed_at")
        return self


def source_is_currently_qualified(
    profile: SourceProfile,
    as_of: datetime,
    scope: str | None = None,
) -> bool:
    _require_aware(as_of, "as_of")
    return (
        profile.qualification_status == "qualified"
        and profile.assessed_at is not None
        and profile.assessed_at <= as_of
        and profile.review_due_at is not None
        and profile.review_due_at >= as_of
        and (scope is None or scope in profile.declared_scopes)
    )


def source_profiles_by_id(
    profiles: Collection[SourceProfile],
) -> dict[str, SourceProfile]:
    indexed: dict[str, SourceProfile] = {}
    for profile in profiles:
        existing = indexed.get(profile.source_id)
        if existing is not None and existing != profile:
            raise ValueError(f"conflicting source profiles: {profile.source_id}")
        indexed[profile.source_id] = profile
    return indexed


class ResearchEpisode(Record):
    schema_version: Literal["2.0"] = "2.0"
    episode_id: NonEmptyText
    source_id: NonEmptyText
    artifact_url: HttpUrl
    title: NonEmptyText
    published_at: datetime
    retrieved_at: datetime
    content_sha256: Sha256
    completeness: MaterialCompleteness
    attribution_quality: AttributionQuality
    supplement_evidence_ids: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def validate_episode(self) -> ResearchEpisode:
        _require_aware(self.published_at, "published_at")
        _require_aware(self.retrieved_at, "retrieved_at")
        expected = episode_id_for(
            self.source_id,
            str(self.artifact_url),
            self.published_at,
            self.content_sha256,
        )
        if self.episode_id != expected:
            raise ValueError("episode_id does not match raw artifact identity")
        if self.retrieved_at < self.published_at:
            raise ValueError("retrieved_at cannot precede published_at")
        return self


def research_episodes_by_id(
    episodes: Collection[ResearchEpisode],
) -> dict[str, ResearchEpisode]:
    indexed: dict[str, ResearchEpisode] = {}
    for episode in episodes:
        existing = indexed.get(episode.episode_id)
        if existing is not None and existing != episode:
            raise ValueError(f"conflicting research episodes: {episode.episode_id}")
        indexed[episode.episode_id] = episode
    return indexed


class EvidenceCapture(Record):
    schema_version: Literal["2.0"] = "2.0"
    evidence_id: NonEmptyText
    url: HttpUrl
    quote: NonEmptyText
    retrieved_at: datetime
    published_at: datetime | None = None
    content_sha256: Sha256
    capture_kind: EvidenceKind

    @model_validator(mode="after")
    def validate_capture(self) -> EvidenceCapture:
        _require_aware(self.retrieved_at, "retrieved_at")
        if self.published_at is not None:
            _require_aware(self.published_at, "published_at")
            if self.published_at > self.retrieved_at:
                raise ValueError("published_at cannot follow retrieved_at")
        expected = evidence_id_for(
            str(self.url), self.quote, self.retrieved_at, self.content_sha256
        )
        if self.evidence_id != expected:
            raise ValueError("evidence_id does not match captured content")
        return self


class Assertion(Record):
    assertion_id: NonEmptyText
    statement: NonEmptyText
    provenance: Provenance
    source_quote: NonEmptyText | None = None
    verdict: EvidenceVerdict = "unverified"
    evidence_ids: tuple[NonEmptyText, ...] = ()
    load_bearing: bool = False

    @model_validator(mode="after")
    def validate_assertion(self) -> Assertion:
        if self.provenance == "stated" and self.source_quote is None:
            raise ValueError("stated assertion requires a source quote")
        if self.verdict in ("supports", "refutes") and not self.evidence_ids:
            raise ValueError("adjudicated assertion requires evidence")
        return self


class SessionHorizon(Record):
    kind: Literal["sessions"] = "sessions"
    sessions: int = Field(gt=0)


class DateHorizon(Record):
    kind: Literal["date"] = "date"
    by_date: date


class EventHorizon(Record):
    kind: Literal["event"] = "event"
    event: NonEmptyText
    by_date: date


Horizon: TypeAlias = Annotated[
    SessionHorizon | DateHorizon | EventHorizon, Field(discriminator="kind")
]


class Expression(Record):
    instrument: NonEmptyText
    direction: Direction
    horizon: Horizon
    origin: ExpressionOrigin
    instrument_provenance: Provenance
    direction_provenance: Provenance
    horizon_provenance: Provenance
    rationale: NonEmptyText
    source_quote: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_origin(self) -> Expression:
        if self.origin == "source":
            dimensions = (
                self.instrument_provenance,
                self.direction_provenance,
                self.horizon_provenance,
            )
            if any(value != "stated" for value in dimensions):
                raise ValueError("source expression requires every dimension to be stated")
            if self.source_quote is None:
                raise ValueError("source expression requires a source quote")
        return self


class Catalyst(Record):
    description: NonEmptyText
    by_date: date
    provenance: Provenance
    evidence_ids: tuple[NonEmptyText, ...]


class MonitoringTrigger(Record):
    description: NonEmptyText
    metric: NonEmptyText
    operator: TriggerOperator
    target_value: NonEmptyText
    review_at: datetime
    evidence_ids: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def validate_trigger(self) -> MonitoringTrigger:
        _require_aware(self.review_at, "review_at")
        return self


class ResearchCase(Record):
    schema_version: Literal["2.0"] = "2.0"
    case_id: NonEmptyText
    source_id: NonEmptyText
    episode_id: NonEmptyText
    scope: NonEmptyText
    opened_at: datetime
    as_of: datetime
    disposition: Disposition
    disposition_reason: NonEmptyText
    thesis: NonEmptyText | None = None
    expectations_gap: NonEmptyText | None = None
    downside: NonEmptyText | None = None
    assertions: tuple[Assertion, ...] = ()
    countercase: NonEmptyText | None = None
    expression: Expression | None = None
    catalyst: Catalyst | None = None
    invalidators: tuple[MonitoringTrigger, ...] = ()
    watch_trigger: MonitoringTrigger | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def validate_case(self) -> ResearchCase:
        _require_aware(self.opened_at, "opened_at")
        _require_aware(self.as_of, "as_of")
        if self.valid_until is not None:
            _require_aware(self.valid_until, "valid_until")
        expected = case_id_for(self.source_id, self.episode_id, self.opened_at)
        if self.case_id != expected:
            raise ValueError("case_id does not match source, episode, and opened_at")
        if self.as_of < self.opened_at:
            raise ValueError("as_of cannot precede opened_at")
        return self


def referenced_evidence_ids(
    case: ResearchCase,
    profile: SourceProfile,
    episode: ResearchEpisode,
) -> tuple[str, ...]:
    evidence_ids = list(profile.qualification_evidence_ids)
    evidence_ids.extend(episode.supplement_evidence_ids)
    for assertion in case.assertions:
        evidence_ids.extend(assertion.evidence_ids)
    if case.catalyst is not None:
        evidence_ids.extend(case.catalyst.evidence_ids)
    for invalidator in case.invalidators:
        evidence_ids.extend(invalidator.evidence_ids)
    if case.watch_trigger is not None:
        evidence_ids.extend(case.watch_trigger.evidence_ids)
    return tuple(sorted(set(evidence_ids)))


class CheckIssue(Record):
    code: CheckIssueCode
    path: NonEmptyText
    message: NonEmptyText


class CheckResult(Record):
    schema_version: Literal["2.0"] = "2.0"
    checker_version: NonEmptyText
    case_id: NonEmptyText
    disposition: Disposition
    digest: Sha256
    valid: bool
    publishable: bool
    issues: tuple[CheckIssue, ...] = ()

    @model_validator(mode="after")
    def validate_result(self) -> CheckResult:
        if self.valid == bool(self.issues):
            raise ValueError("valid must be true exactly when issues is empty")
        if self.publishable and (
            not self.valid or self.disposition != "validated_trade_candidate"
        ):
            raise ValueError("only a valid candidate disposition is publishable")
        return self


class ValidatedCandidate(Record):
    schema_version: Literal["2.0"] = "2.0"
    candidate_id: NonEmptyText
    case_id: NonEmptyText
    source_id: NonEmptyText
    scope: NonEmptyText
    episode_id: NonEmptyText
    disposition: Literal["validated_trade_candidate"] = "validated_trade_candidate"
    check_digest: Sha256
    checker_version: NonEmptyText
    published_at: datetime
    valid_until: datetime
    thesis: NonEmptyText
    expectations_gap: NonEmptyText
    downside: NonEmptyText
    assertions: tuple[Assertion, ...]
    countercase: NonEmptyText
    expression: Expression
    catalyst: Catalyst
    invalidators: tuple[MonitoringTrigger, ...]
    evidence_ids: tuple[NonEmptyText, ...]

    @model_validator(mode="after")
    def validate_candidate(self) -> ValidatedCandidate:
        _require_aware(self.published_at, "published_at")
        _require_aware(self.valid_until, "valid_until")
        if self.candidate_id != candidate_id_for(self.check_digest):
            raise ValueError("candidate_id does not match check digest")
        if self.valid_until <= self.published_at:
            raise ValueError("valid_until must follow published_at")
        if not self.invalidators:
            raise ValueError("validated candidate requires invalidators")
        if self.catalyst.by_date <= self.published_at.date():
            raise ValueError("validated candidate catalyst must be in the future")
        if any(
            invalidator.review_at <= self.published_at
            for invalidator in self.invalidators
        ):
            raise ValueError("validated candidate invalidators must be pending")
        horizon = self.expression.horizon
        if isinstance(horizon, DateHorizon | EventHorizon) and (
            horizon.by_date <= self.published_at.date()
            or horizon.by_date > self.valid_until.date()
        ):
            raise ValueError(
                "validated candidate dated horizon must be future and within validity"
            )
        if not self.evidence_ids:
            raise ValueError("validated candidate requires evidence")
        load_bearing = tuple(
            assertion for assertion in self.assertions if assertion.load_bearing
        )
        if not load_bearing:
            raise ValueError("validated candidate requires a load-bearing assertion")
        if any(
            assertion.verdict != "supports" or assertion.provenance == "missing"
            for assertion in load_bearing
        ):
            raise ValueError(
                "validated candidate requires supported load-bearing assertions "
                "with known provenance"
            )
        if self.catalyst.provenance == "missing" or not self.catalyst.evidence_ids:
            raise ValueError("validated candidate requires an evidenced catalyst")
        expression_provenance = (
            self.expression.instrument_provenance,
            self.expression.direction_provenance,
            self.expression.horizon_provenance,
        )
        if "missing" in expression_provenance:
            raise ValueError(
                "validated candidate expression requires known provenance"
            )
        referenced_evidence = {
            evidence_id
            for assertion in self.assertions
            for evidence_id in assertion.evidence_ids
        }
        referenced_evidence.update(self.catalyst.evidence_ids)
        for invalidator in self.invalidators:
            referenced_evidence.update(invalidator.evidence_ids)
        if not referenced_evidence.issubset(self.evidence_ids):
            raise ValueError("validated candidate is missing referenced evidence IDs")
        if any(
            contains_portfolio_instruction(value)
            for _, value in candidate_instruction_text(self)
        ):
            raise ValueError("validated candidate contains portfolio instructions")
        return self


def candidate_instruction_text(
    record: ResearchCase | ValidatedCandidate,
) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for path, value in (
        ("thesis", record.thesis),
        ("expectations_gap", record.expectations_gap),
        ("downside", record.downside),
        ("countercase", record.countercase),
    ):
        if value is not None:
            values.append((path, value))
    for assertion in record.assertions:
        values.append(
            (f"assertions.{assertion.assertion_id}.statement", assertion.statement)
        )
        if assertion.source_quote is not None:
            values.append(
                (
                    f"assertions.{assertion.assertion_id}.source_quote",
                    assertion.source_quote,
                )
            )
    if record.expression is not None:
        values.extend(
            (
                ("expression.instrument", record.expression.instrument),
                ("expression.rationale", record.expression.rationale),
            )
        )
        if isinstance(record.expression.horizon, EventHorizon):
            values.append(("expression.horizon.event", record.expression.horizon.event))
        if record.expression.source_quote is not None:
            values.append(
                ("expression.source_quote", record.expression.source_quote)
            )
    if record.catalyst is not None:
        values.append(("catalyst.description", record.catalyst.description))
    for index, invalidator in enumerate(record.invalidators):
        values.extend(
            (
                (f"invalidators.{index}.description", invalidator.description),
                (f"invalidators.{index}.metric", invalidator.metric),
                (f"invalidators.{index}.target_value", invalidator.target_value),
            )
        )
    return tuple(values)
