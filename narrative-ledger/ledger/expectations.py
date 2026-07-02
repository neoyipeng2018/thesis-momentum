"""The deterministic reverse-DCF — 'a real DCF calculator' per the research.

The agent gathers cited inputs and interprets the output against base rates;
it never runs the math. Crude Gordon-style solve on purpose: the point is
discipline, not precision.
"""
from __future__ import annotations


def implied_cagr(
    price: float,
    shares_out: float,
    net_debt: float,
    base_fcf: float,
    exit_multiple: float,
    years: int = 5,
    discount: float = 0.10,
) -> float:
    """What FCF growth does today's price already require?

    EV = exit_multiple * base_fcf * (1+g)^years / (1+discount)^years  ->  solve g.
    Every argument arrives as a cited SourceRef from priced_in.inputs.
    """
    if min(price, shares_out, base_fcf, exit_multiple) <= 0:
        raise ValueError("price, shares_out, base_fcf and exit_multiple must be > 0")
    ev = price * shares_out + net_debt
    if ev <= 0:
        raise ValueError("enterprise value must be > 0")
    g = ((ev * (1 + discount) ** years) / (exit_multiple * base_fcf)) ** (1 / years) - 1
    return g


def describe(g: float, **inputs) -> str:
    """Echo the assumptions back so the report can quote them verbatim."""
    kv = ", ".join(f"{k}={v}" for k, v in inputs.items())
    return f"implied FCF CAGR {g:+.1%} ({kv})"
