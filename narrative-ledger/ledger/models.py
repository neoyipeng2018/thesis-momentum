"""The 5-object data contract (plan §03). This file is the single source of truth.

Firewall notes:
- `forecast` is reserved and typed `None`: any non-null value fails structural
  validation before rule checks even run.
- `conviction` / `size_frac` / `outcome` are computed by code, never the agent.
- World numbers (prices, margins, backlogs) must arrive as `SourceRef`s with
  evidence. Bounded judgment scalars (verdicts, gap_score, narrative_stage,
  load_bearing) are the agent's, set against the rubrics in references/.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl

ClaimType = Literal["factual", "valuation", "catalyst", "price", "expression"]
Verdict = Literal["supports", "refutes", "insufficient"]


class Evidence(BaseModel):
    url: HttpUrl
    quote: str  # exact sentence/row carrying the fact — verbatim
    retrieved_at: datetime
    is_primary: bool  # filing/regulator/company vs secondary


class Claim(BaseModel):
    id: str
    type: ClaimType
    author_quote: str  # the source's exact words
    restatement: str  # plain-English, atomic
    load_bearing: bool = False
    verdict: Optional[Verdict] = None  # required iff load_bearing
    evidence: list[Evidence] = []  # required iff load_bearing


class SourceRef(BaseModel):
    value: float  # the number used downstream
    unit: str  # "x EV/EBITDA", "USD", "%" — be descriptive
    evidence: Evidence  # every number is cited — firewall


class TrackRecord(BaseModel):
    n_calls: int
    hit_rate: float  # benchmark-relative, matched horizon
    avg_excess: float
    ci_low: float
    ci_high: float  # Wilson interval on hit_rate
    source_weight: float  # [0,1], shrunk by n — feeds sizing
    status: Literal["unproven", "provisional", "trusted"]


class Source(BaseModel):
    id: str  # "lyn-alden"
    name: str
    venue: HttpUrl
    artifact_url: HttpUrl  # the specific post being read
    published_at: datetime  # public timestamp — anti-leakage anchor
    track_record: TrackRecord  # filled by code from the ledger


class PricedIn(BaseModel):
    ticker: str
    expectations_summary: str  # what price already requires (quotes `cli imply`)
    variant_view: str  # what we believe that differs
    inputs: list[SourceRef]  # cited numbers for the reverse-DCF
    gap_score: float = Field(ge=0, le=1)  # 1 clear gap … 0 fully priced
    narrative_stage: Literal["early", "crowding", "exhausted"]


class KillSwitch(BaseModel):
    condition: str  # measurable + dated
    by_date: date


class Decision(BaseModel):
    verdict: Literal["size", "starter", "wait", "pass"]
    ticker: str
    direction: Literal["long", "short"]
    horizon_sessions: int  # TRADING sessions, pre-committed (~10 thematic)
    kill_switches: list[KillSwitch]  # validate requires >= 3
    conviction: Optional[float] = None  # COMPUTED by code, not agent
    size_frac: Optional[float] = None  # COMPUTED by code, not agent


class Outcome(BaseModel):  # filled at T + horizon by code
    realised_excess: Optional[float] = None  # direction-signed, benchmark-relative
    hit: Optional[bool] = None
    closed_at: Optional[datetime] = None
    kill_switch_fired: Optional[str] = None  # which one, if exit != horizon


class Payload(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    created_at: datetime  # run time; vs source.published_at = your slippage
    source: Source
    claims: list[Claim]
    priced_in: PricedIn
    decision: Decision
    outcome: Outcome = Outcome()
    forecast: None = None  # reserved & must stay null (firewall)
