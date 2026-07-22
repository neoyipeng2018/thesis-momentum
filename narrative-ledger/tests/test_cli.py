from pathlib import Path

from _pytest.capture import CaptureFixture

from ledger.check import check_case
from ledger.cli import main
from ledger.storage import write_model_atomic
from tests.v2_factory import CandidateFixture, candidate_fixture


def _write_records(root: Path, fixture: CandidateFixture) -> Path:
    records = root / "records"
    write_model_atomic(
        records / "sources" / f"{fixture.profile.source_id}.json", fixture.profile
    )
    write_model_atomic(
        records / "episodes" / f"{fixture.episode.episode_id}.json", fixture.episode
    )
    for evidence in fixture.evidence:
        write_model_atomic(
            records / "evidence" / f"{evidence.evidence_id}.json", evidence
        )
    case_path = records / "research" / f"{fixture.case.case_id}.json"
    write_model_atomic(case_path, fixture.case)
    return case_path


def _tree(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def test_cli_check_is_pure_then_publish_is_explicit(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    fixture = candidate_fixture()
    case_path = _write_records(tmp_path, fixture)
    before = _tree(tmp_path)
    checked = check_case(
        fixture.case, fixture.profile, fixture.episode, fixture.evidence
    )

    status = main(["--root", str(tmp_path), "check", str(case_path)])

    assert status == 0
    assert _tree(tmp_path) == before
    assert checked.digest in _captured(capsys)

    status = main(
        [
            "--root",
            str(tmp_path),
            "publish-candidate",
            str(case_path),
            "--expect-digest",
            checked.digest,
            "--published-at",
            "2026-07-22T10:00:00+00:00",
        ]
    )

    assert status == 0
    candidate_paths = list((tmp_path / "records" / "candidates").glob("*.json"))
    assert len(candidate_paths) == 1


def test_cli_candidate_endpoint_and_report(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    fixture = candidate_fixture()
    case_path = _write_records(tmp_path, fixture)
    checked = check_case(
        fixture.case, fixture.profile, fixture.episode, fixture.evidence
    )
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "publish-candidate",
                str(case_path),
                "--expect-digest",
                checked.digest,
                "--published-at",
                "2026-07-22T10:00:00+00:00",
            ]
        )
        == 0
    )
    _captured(capsys)

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "candidates",
                "--as-of",
                "2026-07-22T11:00:00+00:00",
            ]
        )
        == 0
    )
    output = _captured(capsys)
    assert "validated_trade_candidate" in output
    assert checked.digest in output

    candidate_path = next((tmp_path / "records" / "candidates").glob("*.json"))
    report_path = tmp_path / "reports" / "candidate.html"
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "render-candidate",
                str(candidate_path),
                "--output",
                str(report_path),
            ]
        )
        == 0
    )
    assert report_path.is_file()
    assert "Validated trade candidate" in report_path.read_text()


def test_cli_migration_integrity_error_is_structured(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    status = main(["--root", str(tmp_path), "migrate-v2"])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert '"status": "migration_blocked_integrity_error"' in captured.err


def test_cli_report_output_must_be_owned_by_fresh_start(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    fixture = candidate_fixture()
    case_path = _write_records(tmp_path, fixture)
    checked = check_case(
        fixture.case, fixture.profile, fixture.episode, fixture.evidence
    )
    assert main(
        [
            "--root",
            str(tmp_path),
            "publish-candidate",
            str(case_path),
            "--expect-digest",
            checked.digest,
            "--published-at",
            "2026-07-22T10:00:00+00:00",
        ]
    ) == 0
    _captured(capsys)
    candidate_path = next((tmp_path / "records" / "candidates").glob("*.json"))
    escaped = tmp_path / "custom" / "candidate.html"

    status = main(
        [
            "--root",
            str(tmp_path),
            "render-candidate",
            str(candidate_path),
            "--output",
            str(escaped),
        ]
    )

    assert status == 2
    assert not escaped.exists()

    uppercase = tmp_path / "reports" / "candidate.HTML"
    status = main(
        [
            "--root",
            str(tmp_path),
            "render-candidate",
            str(candidate_path),
            "--output",
            str(uppercase),
        ]
    )

    assert status == 2
    assert not uppercase.exists()


def test_cli_full_stops_at_manual_qualification_before_episode_lookup(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    fixture = candidate_fixture()
    probationary = fixture.profile.model_copy(
        update={
            "qualification_status": "probationary",
            "qualification_evidence_ids": (),
            "assessor": None,
            "assessment_method": None,
            "assessed_at": None,
            "review_due_at": None,
        }
    )
    write_model_atomic(
        tmp_path / "records" / "sources" / f"{probationary.source_id}.json",
        probationary,
    )
    case_path = tmp_path / "records" / "research" / f"{fixture.case.case_id}.json"
    write_model_atomic(case_path, fixture.case)

    status = main(
        [
            "--root",
            str(tmp_path),
            "full",
            str(case_path),
            "--start",
            "2026-07-20T00:00:00+00:00",
            "--end",
            "2026-07-21T00:00:00+00:00",
            "--as-of",
            "2026-07-22T09:00:00+00:00",
        ]
    )

    assert status == 0
    output = _captured(capsys)
    assert '"terminal_state": "awaiting_manual_qualification"' in output
    assert "research episode not found" not in output


def test_cli_full_missing_source_stops_before_episode_lookup(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    fixture = candidate_fixture()
    case_path = tmp_path / "records" / "research" / f"{fixture.case.case_id}.json"
    write_model_atomic(case_path, fixture.case)

    status = main(
        [
            "--root",
            str(tmp_path),
            "full",
            str(case_path),
            "--start",
            "2026-07-20T00:00:00+00:00",
            "--end",
            "2026-07-21T00:00:00+00:00",
            "--as-of",
            "2026-07-22T09:00:00+00:00",
        ]
    )

    assert status == 0
    output = _captured(capsys)
    assert '"terminal_state": "source_not_qualified"' in output
    assert "research episode not found" not in output


def _captured(capsys: CaptureFixture[str]) -> str:
    return capsys.readouterr().out
