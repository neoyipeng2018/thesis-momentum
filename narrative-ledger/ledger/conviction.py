"""Conviction, sizing and the verdict band (plan §07). All math, no judgment.

The band closes a loophole: the agent may always be LESS aggressive than the
computed conviction allows (its judgment enters through the inputs and the
right to veto), never more. Unproven sources can never earn 'size'.
"""
from __future__ import annotations

from .models import Payload

STAGE = {"early": 1.0, "crowding": 0.5, "exhausted": 0.0}
VOL_TARGET_FRAC = 0.10  # max risk budget per idea (tunable)
FLOOR = {"size": 0.35, "starter": 0.15}  # conviction floors per verdict


def attach(p: Payload) -> None:
    """Compute conviction and size_frac in place. Pure math on agent inputs."""
    lb = [c for c in p.claims if c.load_bearing]
    r_verify = sum(c.verdict == "supports" for c in lb) / max(len(lb), 1)

    conviction = (
        p.source.track_record.source_weight  # who said it
        * r_verify  # is it true
        * p.priced_in.gap_score  # is it priced in
        * STAGE[p.priced_in.narrative_stage]  # is it too late
    )
    p.decision.conviction = round(conviction, 3)

    # wait/pass carry no size; unproven sources are capped at a starter regardless
    if p.decision.verdict not in ("size", "starter"):
        p.decision.size_frac = 0.0
        return
    cap = 0.4 if p.source.track_record.status == "unproven" else 1.0
    p.decision.size_frac = round(VOL_TARGET_FRAC * min(conviction, cap), 4)


def max_verdict(p: Payload) -> str:
    """Most aggressive verdict the computed conviction permits (validate enforces)."""
    c = p.decision.conviction or 0.0
    if c >= FLOOR["size"] and p.source.track_record.status != "unproven":
        return "size"  # unproven sources can never earn 'size', only starter
    return "starter" if c >= FLOOR["starter"] else "wait"
