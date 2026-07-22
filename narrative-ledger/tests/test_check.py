from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import HttpUrl, ValidationError

from ledger.check import check_case
from ledger.models import (
    Assertion,
    AttributionQuality,
    Catalyst,
    DateHorizon,
    Disposition,
    EvidenceCapture,
    EventHorizon,
    Expression,
    MaterialCompleteness,
    MonitoringTrigger,
    ResearchCase,
    ResearchEpisode,
    SourceProfile,
    ValidatedCandidate,
    candidate_id_for,
    case_id_for,
    episode_id_for,
    evidence_id_for,
    source_id_for,
)


NOW = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)
QUALIFICATION_TIME = datetime(2026, 7, 1, tzinfo=timezone.utc)
ARTIFACT_URL = "https://research.example/posts/grid-cycle"
CONTENT_SHA = "a" * 64


def qualified_profile() -> tuple[SourceProfile, EvidenceCapture]:
    venue = "https://research.example"
    source_id = source_id_for(venue)
    qualification_evidence = EvidenceCapture(
        evidence_id=evidence_id_for(
            "https://records.example/source-audit",
            "The archive contains all timestamped calls from the review window.",
            QUALIFICATION_TIME,
            "b" * 64,
        ),
        url=HttpUrl("https://records.example/source-audit"),
        quote="The archive contains all timestamped calls from the review window.",
        retrieved_at=QUALIFICATION_TIME,
        published_at=QUALIFICATION_TIME,
        content_sha256="b" * 64,
        capture_kind="primary",
    )
    profile = SourceProfile(
        source_id=source_id,
        name="Research Example",
        venue=HttpUrl(venue),
        feeds=(HttpUrl("https://research.example/feed"),),
        domains=("research.example",),
        declared_scopes=("us-equities",),
        qualification_status="qualified",
        qualification_evidence_ids=(qualification_evidence.evidence_id,),
        assessor="research-committee",
        assessment_method="prospective archive audit",
        assessed_at=QUALIFICATION_TIME,
        review_due_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    return profile, qualification_evidence


def candidate_case(source_id: str) -> tuple[ResearchCase, tuple[EvidenceCapture, ...]]:
    episode_id = episode_id_for(source_id, ARTIFACT_URL, NOW, CONTENT_SHA)
    opened_at = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
    claim_evidence = EvidenceCapture(
        evidence_id=evidence_id_for(
            "https://filings.example/company/quarterly",
            "Contracted backlog increased during the quarter.",
            NOW,
            "c" * 64,
        ),
        url=HttpUrl("https://filings.example/company/quarterly"),
        quote="Contracted backlog increased during the quarter.",
        retrieved_at=NOW,
        published_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        content_sha256="c" * 64,
        capture_kind="primary",
    )
    catalyst_evidence = EvidenceCapture(
        evidence_id=evidence_id_for(
            "https://exchange.example/calendar/company",
            "The next results announcement is scheduled for 14 August 2026.",
            NOW,
            "d" * 64,
        ),
        url=HttpUrl("https://exchange.example/calendar/company"),
        quote="The next results announcement is scheduled for 14 August 2026.",
        retrieved_at=NOW,
        published_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        content_sha256="d" * 64,
        capture_kind="primary",
    )
    case = ResearchCase(
        case_id=case_id_for(source_id, episode_id, opened_at),
        source_id=source_id,
        episode_id=episode_id,
        scope="us-equities",
        opened_at=opened_at,
        as_of=datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc),
        disposition="validated_trade_candidate",
        disposition_reason="All candidate gates pass on current evidence.",
        thesis="Backlog growth is not yet reflected in the company valuation.",
        expectations_gap="The price implies flat backlog despite verified growth.",
        downside="Conversion delays could compress the current valuation multiple.",
        assertions=(
            Assertion(
                assertion_id="backlog-growth",
                statement="Contracted backlog increased in the latest quarter.",
                provenance="inferred",
                source_quote="Backlog is beginning to inflect.",
                verdict="supports",
                evidence_ids=(claim_evidence.evidence_id,),
                load_bearing=True,
            ),
        ),
        countercase="The backlog may convert more slowly than the market expects.",
        expression=Expression(
            instrument="GRID",
            direction="long",
            horizon=DateHorizon(by_date=date(2026, 10, 31)),
            origin="researcher",
            instrument_provenance="assumed",
            direction_provenance="inferred",
            horizon_provenance="assumed",
            rationale="The listed equity is the most liquid direct expression.",
            source_quote=None,
        ),
        catalyst=Catalyst(
            description="Quarterly results update the backlog conversion rate.",
            by_date=date(2026, 8, 14),
            provenance="stated",
            evidence_ids=(catalyst_evidence.evidence_id,),
        ),
        invalidators=(
            MonitoringTrigger(
                description="Reject the thesis if reported backlog declines.",
                metric="reported backlog growth",
                operator="lt",
                target_value="0%",
                review_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
                evidence_ids=(claim_evidence.evidence_id,),
            ),
        ),
        watch_trigger=None,
        valid_until=datetime(2026, 10, 31, tzinfo=timezone.utc),
    )
    return case, (claim_evidence, catalyst_evidence)


def research_episode(source_id: str) -> ResearchEpisode:
    return ResearchEpisode(
        episode_id=episode_id_for(source_id, ARTIFACT_URL, NOW, CONTENT_SHA),
        source_id=source_id,
        artifact_url=HttpUrl(ARTIFACT_URL),
        title="The grid backlog cycle",
        published_at=NOW,
        retrieved_at=NOW,
        content_sha256=CONTENT_SHA,
        completeness="full",
        attribution_quality="direct",
        supplement_evidence_ids=(),
    )


def validated_candidate() -> ValidatedCandidate:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    checked = check_case(
        case, profile, episode, (qualification_evidence, *case_evidence)
    )
    assert checked.publishable is True
    assert case.thesis is not None
    assert case.expectations_gap is not None
    assert case.downside is not None
    assert case.countercase is not None
    assert case.expression is not None
    assert case.catalyst is not None
    assert case.valid_until is not None
    return ValidatedCandidate(
        candidate_id=candidate_id_for(checked.digest),
        case_id=case.case_id,
        source_id=case.source_id,
        scope=case.scope,
        episode_id=case.episode_id,
        check_digest=checked.digest,
        checker_version=checked.checker_version,
        published_at=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        valid_until=case.valid_until,
        thesis=case.thesis,
        expectations_gap=case.expectations_gap,
        downside=case.downside,
        assertions=case.assertions,
        countercase=case.countercase,
        expression=case.expression,
        catalyst=case.catalyst,
        invalidators=case.invalidators,
        evidence_ids=tuple(
            capture.evidence_id for capture in (qualification_evidence, *case_evidence)
        ),
    )


def test_qualified_researcher_expression_is_publishable_with_stable_digest() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    evidence = (qualification_evidence, *case_evidence)

    first = check_case(case, profile, episode, evidence)
    second = check_case(case, profile, episode, tuple(reversed(evidence)))

    assert first.valid is True
    assert first.publishable is True
    assert first.issues == ()
    assert first.digest == second.digest
    assert len(first.digest) == 64


def test_research_episode_requires_completeness_and_attribution_quality() -> None:
    profile, _ = qualified_profile()
    episode = research_episode(profile.source_id)
    fields = episode.model_dump()

    for required in ("completeness", "attribution_quality"):
        incomplete = dict(fields)
        incomplete.pop(required)
        with pytest.raises(ValidationError):
            ResearchEpisode.model_validate(incomplete)


@pytest.mark.parametrize("completeness", ("preview", "unknown"))
def test_candidate_rejects_incomplete_episode(
    completeness: MaterialCompleteness,
) -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id).model_copy(
        update={"completeness": completeness}
    )

    result = check_case(
        case, profile, episode, (qualification_evidence, *case_evidence)
    )

    assert any(
        issue.code == "episode_incomplete"
        and issue.path == "episode.completeness"
        for issue in result.issues
    )
    assert result.publishable is False


@pytest.mark.parametrize(
    "attribution_quality", ("direct", "author_interview", "quoted_secondary")
)
def test_candidate_accepts_non_reconstructed_attribution(
    attribution_quality: AttributionQuality,
) -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id).model_copy(
        update={"attribution_quality": attribution_quality}
    )

    result = check_case(
        case, profile, episode, (qualification_evidence, *case_evidence)
    )

    assert result.publishable is True
    assert result.issues == ()


def test_candidate_rejects_reconstructed_attribution() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id).model_copy(
        update={"attribution_quality": "reconstructed"}
    )

    result = check_case(
        case, profile, episode, (qualification_evidence, *case_evidence)
    )

    assert any(
        issue.code == "episode_attribution_reconstructed"
        and issue.path == "episode.attribution_quality"
        for issue in result.issues
    )
    assert result.publishable is False


def test_candidate_load_bearing_assertion_requires_primary_evidence() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    claim_evidence, catalyst_evidence = case_evidence
    secondary_claim = EvidenceCapture(
        evidence_id=claim_evidence.evidence_id,
        url=claim_evidence.url,
        quote=claim_evidence.quote,
        retrieved_at=claim_evidence.retrieved_at,
        published_at=claim_evidence.published_at,
        content_sha256=claim_evidence.content_sha256,
        capture_kind="secondary",
    )

    result = check_case(
        case,
        profile,
        episode,
        (qualification_evidence, secondary_claim, catalyst_evidence),
    )

    assert "primary_evidence_required" in {issue.code for issue in result.issues}
    assert result.publishable is False


def test_candidate_rejects_episode_retrieved_after_case_as_of() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    late_episode = ResearchEpisode(
        episode_id=episode.episode_id,
        source_id=episode.source_id,
        artifact_url=episode.artifact_url,
        title=episode.title,
        published_at=episode.published_at,
        retrieved_at=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        content_sha256=episode.content_sha256,
        completeness=episode.completeness,
        attribution_quality=episode.attribution_quality,
        supplement_evidence_ids=episode.supplement_evidence_ids,
    )

    result = check_case(
        case, profile, late_episode, (qualification_evidence, *case_evidence)
    )

    assert "episode_after_as_of" in {issue.code for issue in result.issues}
    assert result.publishable is False


def test_candidate_rejects_qualification_assessed_after_case_as_of() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    future_profile = SourceProfile(
        source_id=profile.source_id,
        name=profile.name,
        venue=profile.venue,
        feeds=profile.feeds,
        domains=profile.domains,
        declared_scopes=profile.declared_scopes,
        qualification_status=profile.qualification_status,
        qualification_evidence_ids=profile.qualification_evidence_ids,
        assessor=profile.assessor,
        assessment_method=profile.assessment_method,
        assessed_at=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        review_due_at=profile.review_due_at,
    )

    result = check_case(
        case, future_profile, episode, (qualification_evidence, *case_evidence)
    )

    assert "qualification_after_as_of" in {issue.code for issue in result.issues}
    assert result.publishable is False


def test_candidate_rejects_qualification_evidence_captured_after_assessment() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    late_retrieval = datetime(2026, 7, 2, tzinfo=timezone.utc)
    late_qualification = qualification_evidence.model_copy(
        update={
            "evidence_id": evidence_id_for(
                str(qualification_evidence.url),
                qualification_evidence.quote,
                late_retrieval,
                qualification_evidence.content_sha256,
            ),
            "retrieved_at": late_retrieval,
        }
    )
    late_profile = profile.model_copy(
        update={
            "qualification_evidence_ids": (late_qualification.evidence_id,)
        }
    )

    result = check_case(
        case, late_profile, episode, (late_qualification, *case_evidence)
    )

    assert "qualification_evidence_after_assessment" in {
        issue.code for issue in result.issues
    }
    assert result.publishable is False


@pytest.mark.parametrize(
    "instruction",
    (
        "Allocate 10% and execute an order.",
        "Buy 100 shares of ACME.",
        "Allocate half the portfolio to ACME.",
        "Enter ACME at $20 and exit at $30.",
        "Set a 10% stop.",
        "Take a 5% position in ACME.",
        "Buy ACME.",
        "Sell ACME now.",
        "Short ACME into earnings.",
        "Place a buy order for ACME.",
        "Allocate $10,000 to ACME.",
        "Hold ACME.",
        "Hang onto our semi names.",
        "We should hang onto our semi names.",
        "Stay long ACME.",
        "Do not sell ACME.",
        "Rotate out of tech.",
        "Rebalance toward energy.",
    ),
)
def test_candidate_rejects_portfolio_instructions_in_research_text(
    instruction: str,
) -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    instructed = case.model_copy(update={"thesis": instruction})

    result = check_case(
        instructed, profile, episode, (qualification_evidence, *case_evidence)
    )

    assert "portfolio_instruction_language" in {
        issue.code for issue in result.issues
    }
    assert result.publishable is False


def test_candidate_instruction_gate_covers_every_rendered_free_text_shape() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    expression = case.expression
    assert expression is not None
    invalidator = case.invalidators[0]
    instructed = case.model_copy(
        update={
            "expression": expression.model_copy(
                update={
                    "instrument": "execute an order",
                    "horizon": EventHorizon(
                        event="sell the position",
                        by_date=date(2026, 10, 31),
                    ),
                }
            ),
            "invalidators": (
                invalidator.model_copy(
                    update={
                        "metric": "sell the position",
                        "target_value": "execute an order",
                    }
                ),
            ),
        }
    )

    result = check_case(
        instructed, profile, episode, (qualification_evidence, *case_evidence)
    )

    instruction_paths = {
        issue.path
        for issue in result.issues
        if issue.code == "portfolio_instruction_language"
    }
    assert instruction_paths == {
        "expression.instrument",
        "expression.horizon.event",
        "invalidators.0.metric",
        "invalidators.0.target_value",
    }


def test_candidate_instruction_gate_covers_source_and_evidence_quotes() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    claim_evidence, catalyst_evidence = case_evidence
    quote = "Allocate 10% to this position."
    instructed_evidence = EvidenceCapture(
        evidence_id=evidence_id_for(
            str(claim_evidence.url),
            quote,
            claim_evidence.retrieved_at,
            claim_evidence.content_sha256,
        ),
        url=claim_evidence.url,
        quote=quote,
        retrieved_at=claim_evidence.retrieved_at,
        published_at=claim_evidence.published_at,
        content_sha256=claim_evidence.content_sha256,
        capture_kind="primary",
    )
    assertion = case.assertions[0].model_copy(
        update={
            "source_quote": quote,
            "evidence_ids": (instructed_evidence.evidence_id,),
        }
    )
    instructed = case.model_copy(update={"assertions": (assertion,)})

    result = check_case(
        instructed,
        profile,
        episode,
        (qualification_evidence, instructed_evidence, catalyst_evidence),
    )

    instruction_paths = {
        issue.path
        for issue in result.issues
        if issue.code == "portfolio_instruction_language"
    }
    assert instruction_paths == {
        "assertions.backlog-growth.source_quote",
        f"evidence.{instructed_evidence.evidence_id}.quote",
    }


def test_candidate_rejects_legacy_quote_as_qualification_evidence() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    legacy_qualification = EvidenceCapture(
        evidence_id=qualification_evidence.evidence_id,
        url=qualification_evidence.url,
        quote=qualification_evidence.quote,
        retrieved_at=qualification_evidence.retrieved_at,
        published_at=qualification_evidence.published_at,
        content_sha256=qualification_evidence.content_sha256,
        capture_kind="quote_only_legacy",
    )

    result = check_case(
        case, profile, episode, (legacy_qualification, *case_evidence)
    )

    assert any(
        issue.code == "legacy_evidence"
        and issue.path == "profile.qualification_evidence_ids"
        for issue in result.issues
    )
    assert result.publishable is False


def test_candidate_rejects_missing_provenance_on_load_bearing_inputs() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    assertion = case.assertions[0]
    catalyst = case.catalyst
    expression = case.expression
    assert catalyst is not None
    assert expression is not None
    missing_assertion = Assertion(
        assertion_id=assertion.assertion_id,
        statement=assertion.statement,
        provenance="missing",
        source_quote=assertion.source_quote,
        verdict=assertion.verdict,
        evidence_ids=assertion.evidence_ids,
        load_bearing=True,
    )
    missing_catalyst = Catalyst(
        description=catalyst.description,
        by_date=catalyst.by_date,
        provenance="missing",
        evidence_ids=catalyst.evidence_ids,
    )
    missing_expression = Expression(
        instrument=expression.instrument,
        direction=expression.direction,
        horizon=expression.horizon,
        origin="researcher",
        instrument_provenance="missing",
        direction_provenance="missing",
        horizon_provenance="missing",
        rationale=expression.rationale,
        source_quote=None,
    )
    missing_case = case.model_copy(
        update={
            "assertions": (missing_assertion,),
            "catalyst": missing_catalyst,
            "expression": missing_expression,
        }
    )

    result = check_case(
        missing_case, profile, episode, (qualification_evidence, *case_evidence)
    )

    missing_paths = {
        issue.path for issue in result.issues if issue.code == "missing_provenance"
    }
    assert missing_paths == {
        "assertions.backlog-growth.provenance",
        "catalyst.provenance",
        "expression.instrument_provenance",
        "expression.direction_provenance",
        "expression.horizon_provenance",
    }
    assert result.publishable is False


def test_candidate_catalyst_requires_evidence() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    catalyst = case.catalyst
    assert catalyst is not None
    catalyst_without_evidence = Catalyst(
        description=catalyst.description,
        by_date=catalyst.by_date,
        provenance=catalyst.provenance,
        evidence_ids=(),
    )
    incomplete_case = case.model_copy(update={"catalyst": catalyst_without_evidence})

    result = check_case(
        incomplete_case, profile, episode, (qualification_evidence, *case_evidence)
    )

    assert "catalyst_evidence_required" in {
        issue.code for issue in result.issues
    }
    assert result.publishable is False


def test_candidate_catalyst_must_be_future_at_case_as_of() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    catalyst = case.catalyst
    assert catalyst is not None
    due_case = case.model_copy(
        update={
            "catalyst": catalyst.model_copy(update={"by_date": case.as_of.date()})
        }
    )

    result = check_case(
        due_case, profile, episode, (qualification_evidence, *case_evidence)
    )

    assert "catalyst_due" in {issue.code for issue in result.issues}
    assert result.publishable is False


@pytest.mark.parametrize(
    "horizon",
    (
        DateHorizon(by_date=date(2026, 7, 22)),
        EventHorizon(event="earnings", by_date=date(2026, 7, 22)),
    ),
)
def test_candidate_dated_horizon_must_be_future_at_case_as_of(
    horizon: DateHorizon | EventHorizon,
) -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    expression = case.expression
    assert expression is not None
    stale_case = case.model_copy(
        update={"expression": expression.model_copy(update={"horizon": horizon})}
    )

    result = check_case(
        stale_case, profile, episode, (qualification_evidence, *case_evidence)
    )

    assert "invalid_expression_horizon" in {
        issue.code for issue in result.issues
    }
    assert result.publishable is False


def test_candidate_dated_horizon_cannot_exceed_validity_window() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    expression = case.expression
    assert expression is not None
    beyond_validity = case.model_copy(
        update={
            "expression": expression.model_copy(
                update={"horizon": DateHorizon(by_date=date(2026, 11, 1))}
            )
        }
    )

    result = check_case(
        beyond_validity,
        profile,
        episode,
        (qualification_evidence, *case_evidence),
    )

    assert "invalid_expression_horizon" in {
        issue.code for issue in result.issues
    }
    assert result.publishable is False


def test_validated_candidate_persists_checked_evaluator_version() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    checked = check_case(
        case, profile, episode, (qualification_evidence, *case_evidence)
    )
    assert checked.publishable is True
    assert case.thesis is not None
    assert case.expectations_gap is not None
    assert case.downside is not None
    assert case.countercase is not None
    assert case.expression is not None
    assert case.catalyst is not None
    assert case.valid_until is not None
    fields = {
        "candidate_id": candidate_id_for(checked.digest),
        "case_id": case.case_id,
        "source_id": case.source_id,
        "scope": case.scope,
        "episode_id": case.episode_id,
        "check_digest": checked.digest,
        "checker_version": checked.checker_version,
        "published_at": datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        "valid_until": case.valid_until,
        "thesis": case.thesis,
        "expectations_gap": case.expectations_gap,
        "downside": case.downside,
        "assertions": case.assertions,
        "countercase": case.countercase,
        "expression": case.expression,
        "catalyst": case.catalyst,
        "invalidators": case.invalidators,
        "evidence_ids": tuple(
            capture.evidence_id for capture in (qualification_evidence, *case_evidence)
        ),
    }

    candidate = ValidatedCandidate.model_validate(fields)

    assert candidate.checker_version == checked.checker_version
    candidate_fields = candidate.model_dump()
    for prohibited in (
        "allocation",
        "position",
        "order",
        "execution",
        "conviction",
        "size",
        "source_score",
        "forecast",
        "outcome",
    ):
        with pytest.raises(ValidationError):
            ValidatedCandidate.model_validate(
                candidate_fields | {prohibited: "forbidden"}
            )
    fields.pop("checker_version")
    with pytest.raises(ValidationError):
        ValidatedCandidate.model_validate(fields)


def test_watch_requires_a_future_measurable_trigger() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    watch_without_trigger = case.model_copy(
        update={"disposition": "watch", "watch_trigger": None}
    )

    missing = check_case(
        watch_without_trigger,
        profile,
        episode,
        (qualification_evidence, *case_evidence),
    )

    assert {issue.code for issue in missing.issues} == {"watch_trigger_required"}
    trigger = MonitoringTrigger(
        description="Revisit when the next results release is published.",
        metric="quarterly results release",
        operator="published",
        target_value="Q2 2026 results",
        review_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
    )
    watch_with_trigger = watch_without_trigger.model_copy(
        update={"watch_trigger": trigger}
    )

    accepted = check_case(
        watch_with_trigger,
        profile,
        episode,
        (qualification_evidence, *case_evidence),
    )

    assert accepted.valid is True
    assert accepted.publishable is False


def test_probationary_source_cannot_pass_underwriting() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    probationary = profile.model_copy(update={"qualification_status": "probationary"})

    result = check_case(
        case,
        probationary,
        episode,
        (qualification_evidence, *case_evidence),
    )

    assert "source_not_qualified" in {issue.code for issue in result.issues}
    assert result.publishable is False


def test_inferred_source_direction_must_be_researcher_owned() -> None:
    with pytest.raises(ValidationError, match="every dimension to be stated"):
        Expression(
            instrument="GRID",
            direction="long",
            horizon=DateHorizon(by_date=date(2026, 10, 31)),
            origin="source",
            instrument_provenance="stated",
            direction_provenance="inferred",
            horizon_provenance="stated",
            rationale="The source names the instrument but not the direction.",
            source_quote="GRID could benefit from the cycle.",
        )


def test_every_research_case_requires_a_disposition_reason() -> None:
    profile, _ = qualified_profile()
    case, _ = candidate_case(profile.source_id)
    fields = case.model_dump()
    fields.pop("disposition_reason")

    with pytest.raises(ValidationError):
        ResearchCase.model_validate(fields)


def test_research_case_rejects_portfolio_and_execution_fields() -> None:
    profile, _ = qualified_profile()
    case, _ = candidate_case(profile.source_id)
    fields = case.model_dump()

    for prohibited in (
        "allocation",
        "position",
        "order",
        "execution",
        "conviction",
        "size",
        "source_score",
        "forecast",
        "outcome",
    ):
        with pytest.raises(ValidationError):
            ResearchCase.model_validate(fields | {prohibited: "forbidden"})


def test_validated_candidate_enforces_structural_gate_invariants() -> None:
    candidate = validated_candidate()
    assertion = candidate.assertions[0]
    unsupported = Assertion(
        assertion_id=assertion.assertion_id,
        statement=assertion.statement,
        provenance="missing",
        source_quote=assertion.source_quote,
        verdict="insufficient",
        evidence_ids=assertion.evidence_ids,
        load_bearing=True,
    )
    fields = candidate.model_dump()
    fields["assertions"] = (unsupported,)

    with pytest.raises(ValidationError):
        ValidatedCandidate.model_validate(fields)


@pytest.mark.parametrize(
    "disposition",
    ("unscorable", "no_actionable_thesis", "insufficient_material", "reject"),
)
def test_terminal_refusals_are_valid_but_never_publishable(
    disposition: Disposition,
) -> None:
    profile, qualification_evidence = qualified_profile()
    episode = research_episode(profile.source_id)
    opened_at = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
    case = ResearchCase(
        case_id=case_id_for(profile.source_id, episode.episode_id, opened_at),
        source_id=profile.source_id,
        episode_id=episode.episode_id,
        scope="us-equities",
        opened_at=opened_at,
        as_of=datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc),
        disposition=disposition,
        disposition_reason="The research pass ended honestly at this disposition.",
    )

    result = check_case(case, profile, episode, (qualification_evidence,))

    assert result.valid is True
    assert result.publishable is False
    assert result.disposition == disposition


def test_conflicting_capture_metadata_fails_deterministically() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    claim_evidence, catalyst_evidence = case_evidence
    conflicting_claim = EvidenceCapture(
        evidence_id=claim_evidence.evidence_id,
        url=claim_evidence.url,
        quote=claim_evidence.quote,
        retrieved_at=claim_evidence.retrieved_at,
        published_at=claim_evidence.published_at,
        content_sha256=claim_evidence.content_sha256,
        capture_kind="secondary",
    )
    captures = (
        qualification_evidence,
        claim_evidence,
        conflicting_claim,
        catalyst_evidence,
    )

    first = check_case(case, profile, episode, captures)
    second = check_case(case, profile, episode, tuple(reversed(captures)))

    assert first.digest == second.digest
    assert "conflicting_evidence_capture" in {
        issue.code for issue in first.issues
    }
    assert first.publishable is False


def test_unreferenced_evidence_does_not_change_check_digest() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    referenced = (qualification_evidence, *case_evidence)
    unrelated = EvidenceCapture(
        evidence_id=evidence_id_for(
            "https://filings.example/unrelated",
            "This capture is unrelated to the research case.",
            NOW,
            "e" * 64,
        ),
        url=HttpUrl("https://filings.example/unrelated"),
        quote="This capture is unrelated to the research case.",
        retrieved_at=NOW,
        published_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        content_sha256="e" * 64,
        capture_kind="primary",
    )

    without_unrelated = check_case(case, profile, episode, referenced)
    with_unrelated = check_case(case, profile, episode, (*referenced, unrelated))

    assert without_unrelated.digest == with_unrelated.digest
    assert with_unrelated.publishable is True


def test_episode_supplement_reference_must_resolve() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    episode_with_missing_supplement = ResearchEpisode(
        episode_id=episode.episode_id,
        source_id=episode.source_id,
        artifact_url=episode.artifact_url,
        title=episode.title,
        published_at=episode.published_at,
        retrieved_at=episode.retrieved_at,
        content_sha256=episode.content_sha256,
        completeness=episode.completeness,
        attribution_quality=episode.attribution_quality,
        supplement_evidence_ids=("ev_missing-supplement",),
    )

    result = check_case(
        case,
        profile,
        episode_with_missing_supplement,
        (qualification_evidence, *case_evidence),
    )

    assert "missing_evidence" in {issue.code for issue in result.issues}
    assert result.publishable is False


def test_candidate_rejects_evidence_captured_after_case_as_of() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    claim_evidence, catalyst_evidence = case_evidence
    late_retrieval = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    late_claim = EvidenceCapture(
        evidence_id=evidence_id_for(
            str(claim_evidence.url),
            claim_evidence.quote,
            late_retrieval,
            claim_evidence.content_sha256,
        ),
        url=claim_evidence.url,
        quote=claim_evidence.quote,
        retrieved_at=late_retrieval,
        published_at=claim_evidence.published_at,
        content_sha256=claim_evidence.content_sha256,
        capture_kind="primary",
    )
    assertion = case.assertions[0]
    late_assertion = Assertion(
        assertion_id=assertion.assertion_id,
        statement=assertion.statement,
        provenance=assertion.provenance,
        source_quote=assertion.source_quote,
        verdict=assertion.verdict,
        evidence_ids=(late_claim.evidence_id,),
        load_bearing=True,
    )
    invalidator = case.invalidators[0]
    late_invalidator = MonitoringTrigger(
        description=invalidator.description,
        metric=invalidator.metric,
        operator=invalidator.operator,
        target_value=invalidator.target_value,
        review_at=invalidator.review_at,
        evidence_ids=(late_claim.evidence_id,),
    )
    late_case = case.model_copy(
        update={
            "assertions": (late_assertion,),
            "invalidators": (late_invalidator,),
        }
    )

    result = check_case(
        late_case,
        profile,
        episode,
        (qualification_evidence, late_claim, catalyst_evidence),
    )

    assert "evidence_after_as_of" in {issue.code for issue in result.issues}
    assert result.publishable is False


def test_candidate_cannot_reuse_legacy_quotes_for_spine_or_catalyst() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    claim_evidence, catalyst_evidence = case_evidence
    legacy_claim = claim_evidence.model_copy(
        update={"capture_kind": "quote_only_legacy"}
    )
    legacy_catalyst = catalyst_evidence.model_copy(
        update={"capture_kind": "quote_only_legacy"}
    )

    result = check_case(
        case,
        profile,
        episode,
        (qualification_evidence, legacy_claim, legacy_catalyst),
    )

    legacy_paths = {
        issue.path for issue in result.issues if issue.code == "legacy_evidence"
    }
    assert legacy_paths == {
        "assertions.backlog-growth.evidence_ids",
        "catalyst.evidence_ids",
    }
    assert result.publishable is False


def test_case_episode_and_source_links_are_checked() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    other_source_id = source_id_for("https://other-research.example")
    other_episode_id = episode_id_for(
        other_source_id, ARTIFACT_URL, NOW, CONTENT_SHA
    )
    other_episode = ResearchEpisode(
        episode_id=other_episode_id,
        source_id=other_source_id,
        artifact_url=HttpUrl(ARTIFACT_URL),
        title="The grid backlog cycle",
        published_at=NOW,
        retrieved_at=NOW,
        content_sha256=CONTENT_SHA,
        completeness="full",
        attribution_quality="direct",
    )

    result = check_case(
        case,
        profile,
        other_episode,
        (qualification_evidence, *case_evidence),
    )

    codes = {issue.code for issue in result.issues}
    assert "case_episode_mismatch" in codes
    assert "episode_source_mismatch" in codes
    assert result.publishable is False


def test_digest_binds_full_referenced_capture_and_episode_content() -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    claim_evidence, catalyst_evidence = case_evidence
    baseline = check_case(
        case,
        profile,
        episode,
        (qualification_evidence, claim_evidence, catalyst_evidence),
    )
    secondary_catalyst = catalyst_evidence.model_copy(
        update={"capture_kind": "secondary"}
    )
    changed_capture = check_case(
        case,
        profile,
        episode,
        (qualification_evidence, claim_evidence, secondary_catalyst),
    )
    retitled_episode = episode.model_copy(update={"title": "Revised artifact title"})
    changed_episode = check_case(
        case,
        profile,
        retitled_episode,
        (qualification_evidence, claim_evidence, catalyst_evidence),
    )

    assert baseline.publishable is True
    assert changed_capture.publishable is True
    assert changed_episode.publishable is True
    assert len({baseline.digest, changed_capture.digest, changed_episode.digest}) == 3


def test_check_is_pure_and_does_not_mutate_inputs_or_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile, qualification_evidence = qualified_profile()
    case, case_evidence = candidate_case(profile.source_id)
    episode = research_episode(profile.source_id)
    evidence = (qualification_evidence, *case_evidence)
    before = (
        profile.model_dump_json(),
        episode.model_dump_json(),
        case.model_dump_json(),
        tuple(capture.model_dump_json() for capture in evidence),
    )
    monkeypatch.chdir(tmp_path)

    check_case(case, profile, episode, evidence)

    after = (
        profile.model_dump_json(),
        episode.model_dump_json(),
        case.model_dump_json(),
        tuple(capture.model_dump_json() for capture in evidence),
    )
    assert after == before
    assert tuple(tmp_path.iterdir()) == ()
