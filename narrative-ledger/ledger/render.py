"""Decision-first HTML report (plan §5.6). A thin Jinja2 pass — the report is a
by-product; the payload is the product."""
from __future__ import annotations

import datetime as dt
import pathlib

from jinja2 import Environment, FileSystemLoader

from .models import Payload

ROOT = pathlib.Path(__file__).resolve().parent.parent


def render(payload: Payload, out_path: str | pathlib.Path) -> None:
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
    lb = [c for c in payload.claims if c.load_bearing]
    verified = sum(c.verdict == "supports" for c in lb)
    html = env.get_template("report.html.j2").render(
        p=payload,
        verified=verified,
        total_lb=len(lb),
        verified_pct=verified / max(len(lb), 1),
        headline=(
            f"{payload.decision.verdict.upper()} · {payload.decision.ticker} "
            f"· {payload.decision.direction} · {payload.decision.horizon_sessions} sess "
            f"· conv {payload.decision.conviction:.2f}"
        ),
        generated_at=dt.datetime.now(dt.timezone.utc).strftime("%d %b %Y %H:%M UTC"),
    )
    pathlib.Path(out_path).write_text(html)
