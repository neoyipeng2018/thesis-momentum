"""The only place prices enter (plan §5.3).

Conventions (all load-bearing):
  - entry is the first close on a session strictly AFTER the publish date
    (daily bars can't see intraday time; skipping the publish-day close is the
    conservative, deterministic reading of "first close after the timestamp")
  - horizon counts TRADING sessions, not calendar days
  - an immature call returns None — we never score a shorter window silently

Verified against yfinance 1.5: end+period windows backward from end (leak-free);
multi_level_index=False is required for a single ticker to get a Series.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import yfinance as yf


def _rsi(px: pd.Series, n: int = 14) -> float:
    delta = px.diff()
    up = delta.clip(lower=0).rolling(n).mean()
    down = (-delta.clip(upper=0)).rolling(n).mean()
    rs = up / down
    return float((100 - 100 / (1 + rs)).iloc[-1])


def technicals(ticker: str, asof: dt.date | None = None) -> dict:
    """Dated technical snapshot for the narrative-stage / extension read."""
    asof = asof or dt.date.today()
    px = yf.download(
        ticker,
        end=asof + dt.timedelta(days=1),
        period="2y",
        auto_adjust=True,
        progress=False,
        multi_level_index=False,  # else a 1-col DataFrame (yfinance >= 1.5)
    )["Close"].dropna()
    if len(px) < 200:
        raise ValueError(f"insufficient history for {ticker} (n={len(px)})")
    ma50, ma200 = px.rolling(50).mean(), px.rolling(200).mean()
    last = float(px.iloc[-1])
    return {
        "ticker": ticker,
        "asof": str(px.index[-1].date()),
        "price": round(last, 2),
        "above_200dma": bool(last > float(ma200.iloc[-1])),
        "dist_50dma_pct": round(last / float(ma50.iloc[-1]) - 1, 4),
        "dist_200dma_pct": round(last / float(ma200.iloc[-1]) - 1, 4),
        "rsi14": round(_rsi(px), 1),
        "ret_3m_pct": round(float(px.iloc[-1] / px.iloc[-64] - 1), 4) if len(px) > 64 else None,
    }


def _naive_utc(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return t


def forward_excess(
    ticker: str,
    published_at: dt.datetime,
    horizon_sessions: int,
    benchmark: str = "SPY",
) -> float | None:
    """Excess return over `horizon_sessions` trading sessions vs the benchmark,
    entering at the first close on a session after the publish date.
    Returns None until matured. Positive = ticker beat benchmark (long-neutral;
    the caller signs it by direction)."""
    if ticker == benchmark:
        raise ValueError("benchmark must differ from the ticker")
    pub = _naive_utc(published_at)
    px = yf.download(
        [ticker, benchmark],
        start=pub.date(),
        auto_adjust=True,
        progress=False,
    )["Close"].dropna()
    if getattr(px.index, "tz", None) is not None:
        px.index = px.index.tz_convert("UTC").tz_localize(None)
    px = px.loc[px.index.normalize() > pub.normalize()]  # entry AFTER publish date
    if len(px) <= horizon_sessions:
        return None  # not matured — never score a short window
    a, b = px[ticker], px[benchmark]
    r_a = float(a.iloc[horizon_sessions] / a.iloc[0] - 1)
    r_b = float(b.iloc[horizon_sessions] / b.iloc[0] - 1)
    return r_a - r_b
