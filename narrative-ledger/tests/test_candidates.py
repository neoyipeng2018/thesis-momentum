from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import HttpUrl, ValidationError

from ledger.candidates import (
    CandidateConflictError,
    CandidatePublicationError,
    StaleCheckError,
    active_candidates,
    list_candidates,
    publish_candidate,
)
from ledger.check import check_case
from ledger.models import (
    DateHorizon,
    EvidenceCapture,
    MonitoringTrigger,
    ValidatedCandidate,
    evidence_id_for,
)
from tests.v2_factory import candidate_fixture


PUBLISHED_AT = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)


def test_publication_is_explicit_atomic_and_idempotent(tmp_path: Path) -> None:
    fixture = candidate_fixture()
    checked = check_case(
        fixture.case, fixture.profile, fixture.episode, fixture.evidence
    )

    first = publish_candidate(
        fixture.case,
        fixture.profile,
        fixture.episode,
        fixture.evidence,
        checked.digest,
        PUBLISHED_AT,
        tmp_path,
    )
    first_mtime = first.path.stat().st_mtime_ns
    second = publish_candidate(
        fixture.case,
        fixture.profile,
        fixture.episode,
        fixture.evidence,
        checked.digest,
        PUBLISHED_AT + timedelta(days=120),
        tmp_path,
    )

    assert first.created is True
    assert second.created is False
    assert second.candidate == first.candidate
    assert second.path.stat().st_mtime_ns == first_mtime
    assert list_candidates(tmp_path) == (first.candidate,)


def test_edited_case_cannot_publish_with_old_digest(tmp_path: Path) -> None:
    fixture = candidate_fixture()
    checked = check_case(
        fixture.case, fixture.profile, fixture.episode, fixture.evidence
    )
    edited = fixture.case.model_copy(update={"thesis": "A materially edited thesis."})

    with pytest.raises(StaleCheckError):
        publish_candidate(
            edited,
            fixture.profile,
            fixture.episode,
            fixture.evidence,
            checked.digest,
            PUBLISHED_AT,
            tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


def test_repeat_publication_rejects_a_tampered_candidate_record(
    tmp_path: Path,
) -> None:
    fixture = candidate_fixture()
    checked = check_case(
        fixture.case, fixture.profile, fixture.episode, fixture.evidence
    )
    first = publish_candidate(
        fixture.case,
        fixture.profile,
        fixture.episode,
        fixture.evidence,
        checked.digest,
        PUBLISHED_AT,
        tmp_path,
    )
    tampered = first.candidate.model_copy(
        update={"thesis": "A model-valid but unbound replacement thesis."}
    )
    first.path.write_text(f"{tampered.model_dump_json(indent=2)}\n")

    with pytest.raises(CandidateConflictError):
        publish_candidate(
            fixture.case,
            fixture.profile,
            fixture.episode,
            fixture.evidence,
            checked.digest,
            PUBLISHED_AT,
            tmp_path,
        )


def test_publication_rechecks_qualification_at_publication_time(
    tmp_path: Path,
) -> None:
    fixture = candidate_fixture()
    profile = fixture.profile.model_copy(
        update={"review_due_at": datetime(2026, 7, 23, tzinfo=timezone.utc)}
    )
    checked = check_case(
        fixture.case, profile, fixture.episode, fixture.evidence
    )

    with pytest.raises(CandidatePublicationError):
        publish_candidate(
            fixture.case,
            profile,
            fixture.episode,
            fixture.evidence,
            checked.digest,
            datetime(2026, 7, 24, tzinfo=timezone.utc),
            tmp_path,
        )


def test_publication_rejects_a_candidate_with_due_research(
    tmp_path: Path,
) -> None:
    fixture = candidate_fixture()
    checked = check_case(
        fixture.case, fixture.profile, fixture.episode, fixture.evidence
    )

    with pytest.raises(CandidatePublicationError):
        publish_candidate(
            fixture.case,
            fixture.profile,
            fixture.episode,
            fixture.evidence,
            checked.digest,
            datetime(2026, 8, 16, tzinfo=timezone.utc),
            tmp_path,
        )


def test_publication_rejects_a_stale_dated_expression_horizon(
    tmp_path: Path,
) -> None:
    fixture = candidate_fixture()
    expression = fixture.case.expression
    assert expression is not None
    case = fixture.case.model_copy(
        update={
            "expression": expression.model_copy(
                update={"horizon": DateHorizon(by_date=date(2026, 8, 1))}
            )
        }
    )
    checked = check_case(case, fixture.profile, fixture.episode, fixture.evidence)
    assert checked.publishable is True

    with pytest.raises(CandidatePublicationError):
        publish_candidate(
            case,
            fixture.profile,
            fixture.episode,
            fixture.evidence,
            checked.digest,
            datetime(2026, 8, 2, tzinfo=timezone.utc),
            tmp_path,
        )


def test_active_candidates_fail_closed_on_source_status(tmp_path: Path) -> None:
    fixture = candidate_fixture()
    checked = check_case(
        fixture.case, fixture.profile, fixture.episode, fixture.evidence
    )
    published = publish_candidate(
        fixture.case,
        fixture.profile,
        fixture.episode,
        fixture.evidence,
        checked.digest,
        PUBLISHED_AT,
        tmp_path,
    ).candidate

    assert active_candidates((published,), (fixture.profile,), PUBLISHED_AT) == (
        published,
    )

    suspended = fixture.profile.model_copy(update={"qualification_status": "suspended"})
    assert active_candidates((published,), (suspended,), PUBLISHED_AT) == ()

    future_assessment = fixture.profile.model_copy(
        update={"assessed_at": PUBLISHED_AT + timedelta(days=1)}
    )
    assert active_candidates((published,), (future_assessment,), PUBLISHED_AT) == ()

    narrowed_scope = fixture.profile.model_copy(update={"declared_scopes": ("fx",)})
    assert active_candidates((published,), (narrowed_scope,), PUBLISHED_AT) == ()


def test_candidate_schema_rejects_portfolio_instruction_fields(tmp_path: Path) -> None:
    fixture = candidate_fixture()
    checked = check_case(
        fixture.case, fixture.profile, fixture.episode, fixture.evidence
    )
    candidate = publish_candidate(
        fixture.case,
        fixture.profile,
        fixture.episode,
        fixture.evidence,
        checked.digest,
        PUBLISHED_AT,
        tmp_path,
    ).candidate
    invalid_json = candidate.model_dump_json()[:-1] + ',"position_size":0.03}'

    with pytest.raises(ValidationError):
        ValidatedCandidate.model_validate_json(invalid_json)
    with pytest.raises(ValidationError):
        ValidatedCandidate.model_validate(
            candidate.model_dump()
            | {"thesis": "Allocate 10% and execute an order."}
        )


def test_candidate_schema_rejects_due_or_out_of_window_research(
    tmp_path: Path,
) -> None:
    fixture = candidate_fixture()
    checked = check_case(
        fixture.case, fixture.profile, fixture.episode, fixture.evidence
    )
    candidate = publish_candidate(
        fixture.case,
        fixture.profile,
        fixture.episode,
        fixture.evidence,
        checked.digest,
        PUBLISHED_AT,
        tmp_path,
    ).candidate
    due_catalyst = candidate.model_copy(
        update={
            "catalyst": candidate.catalyst.model_copy(
                update={"by_date": PUBLISHED_AT.date()}
            )
        }
    )
    due_invalidator = candidate.model_copy(
        update={
            "invalidators": (
                candidate.invalidators[0].model_copy(
                    update={"review_at": PUBLISHED_AT}
                ),
            )
        }
    )
    stale_expression = candidate.expression.model_copy(
        update={"horizon": DateHorizon(by_date=PUBLISHED_AT.date())}
    )
    stale_horizon = candidate.model_copy(update={"expression": stale_expression})
    beyond_validity_expression = candidate.expression.model_copy(
        update={
            "horizon": DateHorizon(
                by_date=candidate.valid_until.date() + timedelta(days=1)
            )
        }
    )
    beyond_validity = candidate.model_copy(
        update={"expression": beyond_validity_expression}
    )

    for invalid in (
        due_catalyst,
        due_invalidator,
        stale_horizon,
        beyond_validity,
    ):
        with pytest.raises(ValidationError):
            ValidatedCandidate.model_validate_json(invalid.model_dump_json())


def test_published_evidence_manifest_includes_episode_supplements(
    tmp_path: Path,
) -> None:
    fixture = candidate_fixture()
    retrieved_at = datetime(2026, 7, 20, 11, 0, tzinfo=timezone.utc)
    url = "https://interviews.example/source/transcript"
    quote = "The source explicitly described the expected grid backlog cycle."
    content_sha256 = "e" * 64
    supplement = EvidenceCapture(
        evidence_id=evidence_id_for(url, quote, retrieved_at, content_sha256),
        url=HttpUrl(url),
        quote=quote,
        retrieved_at=retrieved_at,
        published_at=datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
        content_sha256=content_sha256,
        capture_kind="secondary",
    )
    episode = fixture.episode.model_copy(
        update={"supplement_evidence_ids": (supplement.evidence_id,)}
    )
    evidence = (*fixture.evidence, supplement)
    checked = check_case(fixture.case, fixture.profile, episode, evidence)

    candidate = publish_candidate(
        fixture.case,
        fixture.profile,
        episode,
        evidence,
        checked.digest,
        PUBLISHED_AT,
        tmp_path,
    ).candidate

    assert supplement.evidence_id in candidate.evidence_ids


def test_published_evidence_manifest_includes_watch_trigger_evidence(
    tmp_path: Path,
) -> None:
    fixture = candidate_fixture()
    retrieved_at = datetime(2026, 7, 20, 11, 0, tzinfo=timezone.utc)
    url = "https://exchange.example/calendar/review"
    quote = "A review update is scheduled for 20 August 2026."
    content_sha256 = "e" * 64
    watch_evidence = EvidenceCapture(
        evidence_id=evidence_id_for(url, quote, retrieved_at, content_sha256),
        url=HttpUrl(url),
        quote=quote,
        retrieved_at=retrieved_at,
        published_at=datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
        content_sha256=content_sha256,
        capture_kind="primary",
    )
    watch_trigger = MonitoringTrigger(
        description="Recheck when the review update is published.",
        metric="review update",
        operator="published",
        target_value="August 2026 update",
        review_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        evidence_ids=(watch_evidence.evidence_id,),
    )
    case = fixture.case.model_copy(update={"watch_trigger": watch_trigger})
    evidence = (*fixture.evidence, watch_evidence)
    checked = check_case(case, fixture.profile, fixture.episode, evidence)

    candidate = publish_candidate(
        case,
        fixture.profile,
        fixture.episode,
        evidence,
        checked.digest,
        PUBLISHED_AT,
        tmp_path,
    ).candidate

    assert watch_evidence.evidence_id in candidate.evidence_ids
