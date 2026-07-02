"""The track-record loop (plan §08) — the moat.

- append_call is called by `cli validate` on pass. ONLY code writes calls.csv
  (firewall 5); every verdict is logged, wait/pass included, so the ledger can
  shadow-score the ideas you declined and grade the gate itself.
- score_source: matured-only, per-call horizons, direction-signed excess,
  Beta(2,2) shrink; 'trusted' needs frequency AND positive average excess.
- discrimination = mean(acted excess) - mean(declined excess): does your
  apparatus beat blindly following the feed?
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import pathlib

from . import marketdata
from .models import Payload, TrackRecord

ROOT = pathlib.Path(__file__).resolve().parent.parent  # narrative-ledger/
CALLS = ROOT / "ledger" / "calls.csv"
SCORES = ROOT / "ledger" / "source_scores.json"
COLS = [
    "run_id", "source_id", "published_at", "created_at", "ticker", "direction",
    "horizon_sessions", "verdict", "conviction", "size_frac", "benchmark",
]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d
    return (max(0.0, c - h), min(1.0, c + h))  # clamp float noise at the bounds


def _rows(source_id: str | None = None) -> list[dict]:
    if not CALLS.exists():
        return []
    with open(CALLS) as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if source_id in (None, r["source_id"])]


def append_call(p: Payload, benchmark: str = "SPY") -> bool:
    """Append-only, idempotent on run_id. Returns True if a row was written."""
    if any(r["run_id"] == p.run_id for r in _rows()):
        return False  # already logged — calls are immutable, no rewrites
    exists = CALLS.exists()
    with open(CALLS, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if not exists:
            w.writeheader()
        w.writerow(
            {
                "run_id": p.run_id,
                "source_id": p.source.id,
                "published_at": p.source.published_at.isoformat(),
                "created_at": p.created_at.isoformat(),
                "ticker": p.decision.ticker,
                "direction": p.decision.direction,
                "horizon_sessions": p.decision.horizon_sessions,
                "verdict": p.decision.verdict,
                "conviction": p.decision.conviction,
                "size_frac": p.decision.size_frac,
                "benchmark": benchmark,
            }
        )
    return True


def score_source(source_id: str) -> dict:
    rows = _rows(source_id)
    excs: list[tuple[float, str, str]] = []
    for r in rows:  # only matured calls score
        try:
            x = marketdata.forward_excess(
                r["ticker"],
                dt.datetime.fromisoformat(r["published_at"]),
                int(r["horizon_sessions"]),
                r.get("benchmark") or "SPY",
            )
        except Exception:
            x = None
        if x is not None:
            excs.append((x, r["direction"], r["verdict"]))
    signed = [x if d == "long" else -x for x, d, _ in excs]
    n = len(signed)
    k = sum(s > 0 for s in signed)
    hit = k / n if n else 0.0
    avg = sum(signed) / n if n else 0.0
    lo, hi = wilson(k, n)
    weight = (k + 2) / (n + 4)  # Bayesian shrink toward 0.5 (Beta(2,2) prior)
    # trusted needs frequency AND magnitude — hit rate alone rewards good optics
    status = "unproven" if n < 5 else ("trusted" if (lo > 0.5 and avg > 0) else "provisional")
    acted = [x if d == "long" else -x for x, d, v in excs if v in ("size", "starter")]
    passed = [x if d == "long" else -x for x, d, v in excs if v in ("wait", "pass")]
    discr = (sum(acted) / len(acted) if acted else 0.0) - (
        sum(passed) / len(passed) if passed else 0.0
    )
    return {
        "source_id": source_id,
        "n_logged": len(rows),
        "n_calls": n,  # matured only
        "hit_rate": round(hit, 3),
        "avg_excess": round(avg, 4),
        "ci_low": round(lo, 3),
        "ci_high": round(hi, 3),
        "source_weight": round(weight, 3),
        "status": status,
        "discrimination": round(discr, 4),  # cache/`cli score` only — not a payload field
    }


def track_record_for(source_id: str) -> TrackRecord:
    s = score_source(source_id)
    return TrackRecord(
        n_calls=s["n_calls"],
        hit_rate=s["hit_rate"],
        avg_excess=s["avg_excess"],
        ci_low=s["ci_low"],
        ci_high=s["ci_high"],
        source_weight=s["source_weight"],
        status=s["status"],
    )


def _cache_scores() -> dict:
    ids = sorted({r["source_id"] for r in _rows()})
    scores = {i: score_source(i) for i in ids}
    SCORES.write_text(json.dumps(scores, indent=2))
    return scores


def close_and_rescore(run_dir: str | pathlib.Path, kill_switch: str | None = None) -> None:
    run_dir = pathlib.Path(run_dir)
    p = Payload.model_validate_json((run_dir / "payload.json").read_text())
    if p.outcome.realised_excess is not None:
        print(f"already closed: realised_excess={p.outcome.realised_excess:+.2%}")
        return
    x = marketdata.forward_excess(
        p.decision.ticker, p.source.published_at, p.decision.horizon_sessions
    )
    if x is None:
        print("not matured yet — come back at T+horizon sessions")
        return
    signed = x if p.decision.direction == "long" else -x
    p.outcome.realised_excess = round(signed, 4)
    p.outcome.hit = signed > 0
    p.outcome.closed_at = dt.datetime.now(dt.timezone.utc)
    p.outcome.kill_switch_fired = kill_switch
    (run_dir / "payload.json").write_text(p.model_dump_json(indent=2))
    scores = _cache_scores()
    s = scores.get(p.source.id, {})
    print(
        f"closed {p.run_id}: {p.decision.direction} {p.decision.ticker} "
        f"excess {signed:+.2%} ({'hit' if signed > 0 else 'miss'})\n"
        f"re-scored {p.source.id}: weight={s.get('source_weight')} "
        f"status={s.get('status')} n_matured={s.get('n_calls')} "
        f"discrimination={s.get('discrimination')}"
    )


def open_calls() -> list[dict]:
    """Open runs + kill-switch dates, for `cli watch`."""
    out = []
    if not (ROOT / "runs").exists():
        return out
    for d in sorted((ROOT / "runs").iterdir()):
        f = d / "payload.json"
        if not f.exists():
            continue
        try:
            p = Payload.model_validate_json(f.read_text())
        except Exception:
            continue  # scaffold not yet filled — not a call
        if p.outcome.realised_excess is not None:
            continue
        out.append(
            {
                "run_id": p.run_id,
                "ticker": p.decision.ticker,
                "verdict": p.decision.verdict,
                "direction": p.decision.direction,
                "published_at": str(p.source.published_at.date()),
                "horizon_sessions": p.decision.horizon_sessions,
                "kill_switches": [
                    f"{k.by_date.isoformat()}  {k.condition}" for k in p.decision.kill_switches
                ],
            }
        )
    return out
