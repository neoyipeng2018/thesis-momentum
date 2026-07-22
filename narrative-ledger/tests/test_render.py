import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import cast

import pytest
from pydantic import HttpUrl

from ledger.models import (
    Assertion,
    Catalyst,
    DateHorizon,
    EvidenceCapture,
    EvidenceKind,
    EventHorizon,
    Expression,
    MonitoringTrigger,
    ResearchCase,
    SessionHorizon,
    SourceProfile,
    ValidatedCandidate,
    candidate_id_for,
    case_id_for,
    episode_id_for,
    evidence_id_for,
    source_id_for,
)
from ledger.render import render_candidate


NOW = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)
OPENED_AT = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
PUBLISHED_AT = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
VALID_UNTIL = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
ARTIFACT_URL = "https://research.example/posts/grid-cycle"
ARTIFACT_SHA = "a" * 64
CHECK_DIGEST = "f" * 64
HorizonValue = SessionHorizon | DateHorizon | EventHorizon


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag in {"style", "script"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"}:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth == 0 and data.strip():
            self.parts.append(data.strip())


def _visible_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    return " ".join(parser.parts)


def _capture(
    url: str,
    quote: str,
    content_sha: str,
    kind: EvidenceKind,
) -> EvidenceCapture:
    parsed_url = HttpUrl(url)
    return EvidenceCapture(
        evidence_id=evidence_id_for(str(parsed_url), quote, NOW, content_sha),
        url=parsed_url,
        quote=quote,
        retrieved_at=NOW,
        published_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        content_sha256=content_sha,
        capture_kind=kind,
    )


def _profile(qualification_evidence_id: str) -> SourceProfile:
    venue = HttpUrl("https://research.example")
    return SourceProfile(
        source_id=source_id_for(str(venue)),
        name="Research Example",
        venue=venue,
        feeds=(HttpUrl("https://research.example/feed"),),
        domains=("research.example",),
        declared_scopes=("us-equities",),
        qualification_status="qualified",
        qualification_evidence_ids=(qualification_evidence_id,),
        assessor="research-committee",
        assessment_method="prospective archive audit",
        assessed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        review_due_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )


def _candidate(source_id: str, evidence_id: str) -> ValidatedCandidate:
    episode_id = episode_id_for(source_id, ARTIFACT_URL, NOW, ARTIFACT_SHA)
    expression = Expression(
        instrument="GRID",
        direction="long",
        horizon=DateHorizon(by_date=date(2026, 10, 31)),
        origin="researcher",
        instrument_provenance="assumed",
        direction_provenance="inferred",
        horizon_provenance="assumed",
        rationale="The listed equity is the most direct liquid expression.",
    )
    return ValidatedCandidate(
        candidate_id=candidate_id_for(CHECK_DIGEST),
        case_id=case_id_for(source_id, episode_id, OPENED_AT),
        source_id=source_id,
        scope="us-equities",
        episode_id=episode_id,
        check_digest=CHECK_DIGEST,
        checker_version="2.0.0",
        published_at=PUBLISHED_AT,
        valid_until=VALID_UNTIL,
        thesis="Backlog growth is not yet reflected in the company valuation.",
        expectations_gap="The market implies flat backlog despite verified growth.",
        downside="Conversion delays could weaken the valuation case.",
        assertions=(
            Assertion(
                assertion_id="backlog-growth",
                statement="Contracted backlog increased in the latest quarter.",
                provenance="stated",
                source_quote="Backlog is beginning to inflect.",
                verdict="supports",
                evidence_ids=(evidence_id,),
                load_bearing=True,
            ),
        ),
        countercase="Backlog may convert more slowly than expected.",
        expression=expression,
        catalyst=Catalyst(
            description="Quarterly results update the backlog conversion rate.",
            by_date=date(2026, 8, 14),
            provenance="stated",
            evidence_ids=(evidence_id,),
        ),
        invalidators=(
            MonitoringTrigger(
                description="Invalidate if reported backlog declines.",
                metric="reported backlog growth",
                operator="lt",
                target_value="0%",
                review_at=datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc),
                evidence_ids=(evidence_id,),
            ),
        ),
        evidence_ids=(evidence_id,),
    )


def test_render_candidate_writes_html_with_only_referenced_evidence(
    tmp_path: Path,
) -> None:
    referenced = _capture(
        "https://filings.example/company/quarterly",
        "Contracted backlog increased during the quarter.",
        "b" * 64,
        "primary",
    )
    unrelated = _capture(
        "https://news.example/unrelated",
        "This unrelated quotation must not enter the report.",
        "c" * 64,
        "secondary",
    )
    profile = _profile(referenced.evidence_id)
    candidate = _candidate(profile.source_id, referenced.evidence_id)
    output = tmp_path / "candidate.html"

    render_candidate(candidate, profile, (unrelated, referenced), output)

    html = output.read_text()
    assert "LONG GRID — validated research candidate" in html
    assert "Research Example" in html
    assert "us-equities" in html
    assert referenced.quote in html
    assert str(referenced.url) in html
    assert unrelated.quote not in html
    assert str(unrelated.url) not in html


@pytest.mark.parametrize(
    ("horizon", "expected"),
    (
        (SessionHorizon(sessions=1), "1 session"),
        (SessionHorizon(sessions=10), "10 sessions"),
        (DateHorizon(by_date=date(2026, 10, 31)), "through 2026-10-31"),
        (
            EventHorizon(event="regulatory decision", by_date=date(2026, 9, 30)),
            "regulatory decision by 2026-09-30",
        ),
    ),
)
def test_render_candidate_formats_each_horizon_deterministically(
    tmp_path: Path,
    horizon: HorizonValue,
    expected: str,
) -> None:
    evidence = _capture(
        "https://filings.example/company/quarterly",
        "Contracted backlog increased during the quarter.",
        "b" * 64,
        "primary",
    )
    profile = _profile(evidence.evidence_id)
    candidate = _candidate(profile.source_id, evidence.evidence_id)
    expression = candidate.expression.model_copy(update={"horizon": horizon})
    candidate = candidate.model_copy(update={"expression": expression})
    output = tmp_path / f"{horizon.kind}.html"

    render_candidate(candidate, profile, (evidence,), output)

    assert expected in _visible_text(output.read_text())


def test_render_candidate_exposes_provenance_origin_and_trigger_details(
    tmp_path: Path,
) -> None:
    evidence = _capture(
        "https://filings.example/company/quarterly",
        "Contracted backlog increased during the quarter.",
        "b" * 64,
        "primary",
    )
    profile = _profile(evidence.evidence_id)
    candidate = _candidate(profile.source_id, evidence.evidence_id)
    candidate = candidate.model_copy(
        update={
            "assertions": candidate.assertions
            + (
                Assertion(
                    assertion_id="inferred-demand",
                    statement="Demand remains durable.",
                    provenance="inferred",
                ),
                Assertion(
                    assertion_id="assumed-conversion",
                    statement="Backlog converts within the research horizon.",
                    provenance="assumed",
                ),
                Assertion(
                    assertion_id="missing-competitor-response",
                    statement="Competitor response is not stated.",
                    provenance="missing",
                ),
            )
        }
    )
    output = tmp_path / "candidate.html"

    render_candidate(candidate, profile, (evidence,), output)

    text = _visible_text(output.read_text())
    for label in ("stated", "inferred", "assumed", "missing"):
        assert label in text
    assert "researcher" in text
    assert "instrument assumed · direction inferred · horizon assumed" in text
    assert "Provenance: stated." in text
    assert "2026-08-15 09:00 UTC" in text
    assert "reported backlog growth < 0%" in text
    assert "qualified" in text
    assert "primary" in text
    assert candidate.expectations_gap in text
    assert candidate.downside in text
    assert candidate.countercase in text
    assert candidate.candidate_id in text
    assert candidate.case_id in text
    assert candidate.episode_id in text
    assert candidate.check_digest in text
    assert "evaluator 2.0.0" in text


def test_render_candidate_rejects_a_research_case_draft(tmp_path: Path) -> None:
    evidence = _capture(
        "https://filings.example/company/quarterly",
        "Contracted backlog increased during the quarter.",
        "b" * 64,
        "primary",
    )
    profile = _profile(evidence.evidence_id)
    candidate = _candidate(profile.source_id, evidence.evidence_id)
    draft = ResearchCase(
        case_id=candidate.case_id,
        source_id=candidate.source_id,
        episode_id=candidate.episode_id,
        scope="us-equities",
        opened_at=OPENED_AT,
        as_of=datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc),
        disposition="validated_trade_candidate",
        disposition_reason="Every candidate gate passes.",
        thesis=candidate.thesis,
        expectations_gap=candidate.expectations_gap,
        downside=candidate.downside,
        assertions=candidate.assertions,
        countercase=candidate.countercase,
        expression=candidate.expression,
        catalyst=candidate.catalyst,
        invalidators=candidate.invalidators,
        valid_until=candidate.valid_until,
    )

    with pytest.raises(TypeError, match="ValidatedCandidate"):
        render_candidate(
            cast(ValidatedCandidate, draft),
            profile,
            (evidence,),
            tmp_path / "candidate.html",
        )


def test_rendered_visible_text_contains_no_transaction_instructions(
    tmp_path: Path,
) -> None:
    evidence = _capture(
        "https://filings.example/company/quarterly",
        "Contracted backlog increased during the quarter.",
        "b" * 64,
        "primary",
    )
    profile = _profile(evidence.evidence_id)
    candidate = _candidate(profile.source_id, evidence.evidence_id)
    output = tmp_path / "candidate.html"

    render_candidate(candidate, profile, (evidence,), output)

    text = _visible_text(output.read_text()).lower()
    assert "not an instruction to transact" in text
    prohibited = (
        r"\ballocat(?:e|ed|es|ing|ion|ions)\b",
        r"\bconviction\b",
        r"\bexecut(?:e|ed|es|ing|ion)\b",
        r"\border(?:ed|ing|s)?\b",
        r"\bposition(?:ed|ing|s)?\b",
        r"\bsiz(?:e|ed|es|ing)\b",
    )
    for pattern in prohibited:
        assert re.search(pattern, text) is None


def test_render_candidate_rejects_instruction_language_in_evidence(
    tmp_path: Path,
) -> None:
    quote = "Allocate 10% to this position."
    evidence = _capture(
        "https://filings.example/company/quarterly",
        quote,
        "b" * 64,
        "primary",
    )
    profile = _profile(evidence.evidence_id)
    candidate = _candidate(profile.source_id, evidence.evidence_id)

    with pytest.raises(ValueError, match="portfolio instructions"):
        render_candidate(
            candidate,
            profile,
            (evidence,),
            tmp_path / "candidate.html",
        )


def test_render_candidate_fails_closed_when_scope_is_no_longer_qualified(
    tmp_path: Path,
) -> None:
    evidence = _capture(
        "https://filings.example/company/quarterly",
        "Contracted backlog increased during the quarter.",
        "b" * 64,
        "primary",
    )
    profile = _profile(evidence.evidence_id).model_copy(
        update={"declared_scopes": ("fx",)}
    )
    candidate = _candidate(profile.source_id, evidence.evidence_id)

    with pytest.raises(ValueError, match="scope"):
        render_candidate(
            candidate,
            profile,
            (evidence,),
            tmp_path / "candidate.html",
        )
