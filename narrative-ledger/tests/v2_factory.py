from dataclasses import dataclass
from datetime import date, datetime, timezone

from pydantic import HttpUrl

from ledger.models import (
    Assertion,
    Catalyst,
    DateHorizon,
    EvidenceCapture,
    Expression,
    MonitoringTrigger,
    ResearchCase,
    ResearchEpisode,
    SourceProfile,
    case_id_for,
    episode_id_for,
    evidence_id_for,
    source_id_for,
)


@dataclass(frozen=True)
class CandidateFixture:
    profile: SourceProfile
    episode: ResearchEpisode
    case: ResearchCase
    evidence: tuple[EvidenceCapture, ...]


def candidate_fixture() -> CandidateFixture:
    published_at = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
    retrieved_at = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
    opened_at = datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)
    as_of = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)
    venue = "https://research.example"
    source_id = source_id_for(venue)
    artifact_url = "https://research.example/posts/grid-cycle"
    artifact_sha = "a" * 64
    episode_id = episode_id_for(source_id, artifact_url, published_at, artifact_sha)

    qualification = _evidence(
        "https://records.example/source-audit",
        "The archive contains every timestamped call in the review window.",
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        "b" * 64,
    )
    claim = _evidence(
        "https://filings.example/company/quarterly",
        "Contracted backlog increased during the quarter.",
        retrieved_at,
        "c" * 64,
    )
    catalyst = _evidence(
        "https://exchange.example/calendar/company",
        "The next results announcement is scheduled for 14 August 2026.",
        retrieved_at,
        "d" * 64,
    )
    profile = SourceProfile(
        source_id=source_id,
        name="Research Example",
        venue=HttpUrl(venue),
        feeds=(HttpUrl("https://research.example/feed"),),
        domains=("research.example",),
        declared_scopes=("us-equities",),
        qualification_status="qualified",
        qualification_evidence_ids=(qualification.evidence_id,),
        assessor="research-committee",
        assessment_method="prospective archive audit",
        assessed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        review_due_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    episode = ResearchEpisode(
        episode_id=episode_id,
        source_id=source_id,
        artifact_url=HttpUrl(artifact_url),
        title="The grid backlog cycle",
        published_at=published_at,
        retrieved_at=retrieved_at,
        content_sha256=artifact_sha,
        completeness="full",
        attribution_quality="direct",
    )
    case = ResearchCase(
        case_id=case_id_for(source_id, episode_id, opened_at),
        source_id=source_id,
        episode_id=episode_id,
        scope="us-equities",
        opened_at=opened_at,
        as_of=as_of,
        disposition="validated_trade_candidate",
        disposition_reason="All qualification, evidence, expectations, and monitoring gates pass.",
        thesis="Backlog growth is not reflected in the current valuation.",
        expectations_gap="The market assumes flat backlog despite verified growth.",
        downside="Conversion delays could undermine the expected earnings path.",
        assertions=(
            Assertion(
                assertion_id="backlog-growth",
                statement="Contracted backlog increased in the latest quarter.",
                provenance="inferred",
                source_quote="Backlog is beginning to inflect.",
                verdict="supports",
                evidence_ids=(claim.evidence_id,),
                load_bearing=True,
            ),
        ),
        countercase="The backlog may convert more slowly than expected.",
        expression=Expression(
            instrument="GRID",
            direction="long",
            horizon=DateHorizon(by_date=date(2026, 10, 31)),
            origin="researcher",
            instrument_provenance="assumed",
            direction_provenance="inferred",
            horizon_provenance="assumed",
            rationale="The listed equity is the most liquid direct expression.",
        ),
        catalyst=Catalyst(
            description="Quarterly results update the backlog conversion rate.",
            by_date=date(2026, 8, 14),
            provenance="stated",
            evidence_ids=(catalyst.evidence_id,),
        ),
        invalidators=(
            MonitoringTrigger(
                description="Reject the thesis if reported backlog declines.",
                metric="reported backlog growth",
                operator="lt",
                target_value="0%",
                review_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
                evidence_ids=(claim.evidence_id,),
            ),
        ),
        valid_until=datetime(2026, 10, 31, tzinfo=timezone.utc),
    )
    return CandidateFixture(profile, episode, case, (qualification, claim, catalyst))


def _evidence(
    url: str, quote: str, retrieved_at: datetime, content_sha256: str
) -> EvidenceCapture:
    return EvidenceCapture(
        evidence_id=evidence_id_for(url, quote, retrieved_at, content_sha256),
        url=HttpUrl(url),
        quote=quote,
        retrieved_at=retrieved_at,
        published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        content_sha256=content_sha256,
        capture_kind="primary",
    )
