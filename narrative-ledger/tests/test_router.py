from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import HttpUrl

from ledger.candidates import publish_candidate
from ledger.check import check_case
from ledger.models import SourceProfile, source_id_for
from ledger.router import full, monitor, scan, scout, underwrite
from tests.v2_factory import candidate_fixture


AS_OF = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)


def test_scout_stops_at_manual_qualification_seam() -> None:
    fixture = candidate_fixture()
    probationary = fixture.profile.model_copy(
        update={"qualification_status": "probationary"}
    )

    result = scout((probationary,))

    assert result.terminal_state == "awaiting_manual_qualification"
    assert result.source_ids == (probationary.source_id,)


def test_direct_underwrite_cannot_bypass_qualification() -> None:
    fixture = candidate_fixture()
    probationary = fixture.profile.model_copy(
        update={"qualification_status": "probationary"}
    )

    result = underwrite(
        fixture.case, probationary, fixture.episode, fixture.evidence
    )

    assert result.terminal_state == "source_not_qualified"
    assert result.check_result is not None
    assert result.check_result.publishable is False


def test_underwrite_reports_future_qualification_as_not_qualified() -> None:
    fixture = candidate_fixture()
    future_assessment = fixture.profile.model_copy(
        update={"assessed_at": datetime(2026, 7, 23, tzinfo=timezone.utc)}
    )

    result = underwrite(
        fixture.case, future_assessment, fixture.episode, fixture.evidence
    )

    assert result.terminal_state == "source_not_qualified"


def test_scan_enumerates_only_current_qualified_source_episodes() -> None:
    fixture = candidate_fixture()

    result = scan(
        (fixture.profile,),
        (fixture.episode,),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        AS_OF,
        AS_OF,
    )

    assert result.terminal_state == "episodes_captured"
    assert result.episode_ids == (fixture.episode.episode_id,)


def test_scan_excludes_qualification_that_is_not_yet_effective() -> None:
    fixture = candidate_fixture()
    future_assessment = fixture.profile.model_copy(
        update={"assessed_at": datetime(2026, 7, 23, tzinfo=timezone.utc)}
    )

    result = scan(
        (future_assessment,),
        (fixture.episode,),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        AS_OF,
        AS_OF,
    )

    assert result.terminal_state == "no_qualified_sources"


def test_scan_reports_no_episodes_without_making_a_thesis_judgment() -> None:
    fixture = candidate_fixture()

    result = scan(
        (fixture.profile,),
        (),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        AS_OF,
        AS_OF,
    )

    assert result.terminal_state == "no_episodes_captured"


def test_scan_deduplicates_identical_episodes_and_rejects_conflicts() -> None:
    fixture = candidate_fixture()

    deduplicated = scan(
        (fixture.profile,),
        (fixture.episode, fixture.episode),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        AS_OF,
        AS_OF,
    )

    assert deduplicated.episode_ids == (fixture.episode.episode_id,)
    conflicting = fixture.episode.model_copy(update={"title": "Conflicting title"})
    with pytest.raises(ValueError, match="conflicting research episodes"):
        scan(
            (fixture.profile,),
            (fixture.episode, conflicting),
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            AS_OF,
            AS_OF,
        )


def test_router_rejects_conflicting_source_profiles() -> None:
    fixture = candidate_fixture()
    suspended = fixture.profile.model_copy(
        update={"qualification_status": "suspended"}
    )

    with pytest.raises(ValueError, match="conflicting source profiles"):
        scout((fixture.profile, suspended))


def test_full_never_crosses_probationary_source_seam() -> None:
    fixture = candidate_fixture()
    probationary = fixture.profile.model_copy(
        update={"qualification_status": "probationary"}
    )

    result = full(
        (probationary,),
        (fixture.episode,),
        fixture.case,
        fixture.evidence,
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 31, tzinfo=timezone.utc),
        fixture.case.as_of,
    )

    assert result.terminal_state == "awaiting_manual_qualification"
    assert result.check_result is None


def test_full_ignores_an_unrelated_probationary_source() -> None:
    fixture = candidate_fixture()
    unrelated_venue = "https://unrelated.example"
    unrelated = SourceProfile(
        source_id=source_id_for(unrelated_venue),
        name="Unrelated Research",
        venue=HttpUrl(unrelated_venue),
        domains=("unrelated.example",),
    )

    result = full(
        (fixture.profile, unrelated),
        (fixture.episode,),
        fixture.case,
        fixture.evidence,
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        fixture.case.as_of,
        fixture.case.as_of,
    )

    assert result.terminal_state == "validated_trade_candidate"


def test_full_requires_one_consistent_as_of_time() -> None:
    fixture = candidate_fixture()

    with pytest.raises(ValueError, match="case as_of"):
        full(
            (fixture.profile,),
            (fixture.episode,),
            fixture.case,
            fixture.evidence,
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            AS_OF,
            datetime(2026, 7, 23, tzinfo=timezone.utc),
        )


def test_monitor_reports_empty_candidate_state() -> None:
    fixture = candidate_fixture()

    result = monitor((), (fixture.profile,), AS_OF)

    assert result.terminal_state == "no_active_candidates"


def test_monitor_requires_research_when_candidate_trigger_is_due(
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
        datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc),
        tmp_path / "candidates",
    ).candidate

    result = monitor(
        (candidate,),
        (fixture.profile,),
        datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc),
    )

    assert result.terminal_state == "research_refresh_required"


def test_monitor_fails_closed_when_candidate_scope_is_no_longer_qualified(
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
        AS_OF,
        tmp_path / "candidates",
    ).candidate
    narrowed_scope = fixture.profile.model_copy(update={"declared_scopes": ("fx",)})

    result = monitor((candidate,), (narrowed_scope,), AS_OF)

    assert result.terminal_state == "source_qualification_suspended"
