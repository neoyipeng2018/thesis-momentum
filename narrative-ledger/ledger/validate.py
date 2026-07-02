"""The deterministic referee (plan §5.5). Nothing renders or sizes until this passes.

Rules enforced here, beyond Pydantic structure:
  - firewall: forecast null; every priced-in number carries a verbatim quote
  - verification: >=2 load-bearing claims, each with verdict + evidence
  - independence (firewall 6): a thesis cannot cite itself
  - decision: >=3 dated kill-switches; refuted spine can't 'size';
    verification rate >= 0.6 to act
  - verdict band: agent may downgrade, never upgrade (conviction.max_verdict)
"""
from __future__ import annotations

from tldextract import extract as _extract

from . import conviction
from .models import Payload

RANK = {"pass": 0, "wait": 1, "starter": 2, "size": 3}
MIN_VERIFICATION_RATE = 0.6


def _dom(url) -> str:
    return _extract(str(url)).registered_domain


def validate(payload: Payload) -> list[str]:
    errs: list[str] = []

    # firewall 1: reserved forecast field must be empty (belt + braces; the
    # type system already rejects non-null before we get here)
    if payload.forecast is not None:
        errs.append("firewall: forecast field must be null")

    # firewall 2: every priced-in number carries citable evidence
    for ref in payload.priced_in.inputs:
        if not ref.evidence.quote.strip():
            errs.append(f"firewall: number {ref.value} {ref.unit} lacks a quote")

    # verification: load-bearing claims need a verdict + INDEPENDENT evidence
    lb = [c for c in payload.claims if c.load_bearing]
    if len(lb) < 2:
        errs.append("need >= 2 load-bearing claims")
    for c in lb:
        if c.verdict is None or not c.evidence:
            errs.append(f"claim {c.id}: load-bearing needs verdict + evidence")
        for ev in c.evidence:  # firewall 6: a thesis cannot cite itself
            if _dom(ev.url) == _dom(payload.source.artifact_url):
                errs.append(f"claim {c.id}: evidence must be independent of the artifact")

    # decision rules
    if len(payload.decision.kill_switches) < 3:
        errs.append("decision: need >= 3 measurable, dated kill-switches")
    if any(c.verdict == "refutes" for c in lb) and payload.decision.verdict == "size":
        errs.append("a refuted load-bearing claim cannot support a full size")

    # gate: verified fraction must clear the bar for anything but wait/pass
    # (n.b. with exactly 2 load-bearing claims this means BOTH — intentional)
    rate = sum(c.verdict == "supports" for c in lb) / max(len(lb), 1)
    if payload.decision.verdict in ("size", "starter") and rate < MIN_VERIFICATION_RATE:
        errs.append(f"verification rate {rate:.0%} too low to act")

    # verdict band: code computes conviction; the agent may downgrade, never upgrade
    conviction.attach(payload)  # pure math on agent inputs
    band = conviction.max_verdict(payload)
    if RANK[payload.decision.verdict] > RANK[band]:
        errs.append(
            f"verdict '{payload.decision.verdict}' exceeds band '{band}' "
            f"(conviction {payload.decision.conviction})"
        )
    return errs
