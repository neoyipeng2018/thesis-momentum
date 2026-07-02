"""Asserts the plan §01 firewall rules (1-6), the verdict band, the sizing caps,
the loop math, and the entry-timing leakage guard."""
import datetime as dt
import json
import pathlib

import pandas as pd
import pytest
from pydantic import ValidationError

from ledger import conviction, expectations, marketdata, trackrecord
from ledger.models import Payload
from ledger.validate import validate

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "sample_payload.json"


def load_fixture() -> Payload:
    return Payload.model_validate_json(FIXTURE.read_text())


def fixture_dict() -> dict:
    return json.loads(FIXTURE.read_text())


# ---------- structure + gate ----------

def test_fixture_passes_the_gate():
    p = load_fixture()
    assert validate(p) == []
    # conviction: 0.5 (unproven weight) * 1.0 (2/2 verified) * 0.6 (gap) * 1.0 (early)
    assert p.decision.conviction == pytest.approx(0.30)
    assert p.decision.size_frac == pytest.approx(0.03)  # 0.10 * min(0.30, 0.40)


def test_firewall_1_forecast_must_be_null():
    d = fixture_dict()
    d["forecast"] = 0.15  # a smuggled return forecast
    with pytest.raises(ValidationError):
        Payload.model_validate(d)


def test_firewall_2_uncited_number_fails():
    p = load_fixture()
    p.priced_in.inputs[0].evidence.quote = "   "
    assert any("lacks a quote" in e for e in validate(p))


def test_firewall_6_self_citation_fails():
    p = load_fixture()
    d = fixture_dict()
    d["claims"][0]["evidence"][0]["url"] = "https://www.samplewriter.com/p/the-thesis-part-2"
    p = Payload.model_validate(d)
    assert any("independent" in e for e in validate(p))


def test_kill_switches_minimum():
    p = load_fixture()
    p.decision.kill_switches = p.decision.kill_switches[:2]
    assert any("kill-switches" in e for e in validate(p))


def test_load_bearing_needs_verdict_and_evidence():
    d = fixture_dict()
    d["claims"][0]["verdict"] = None
    p = Payload.model_validate(d)
    assert any("needs verdict + evidence" in e for e in validate(p))


def test_refuted_spine_cannot_size():
    d = fixture_dict()
    d["claims"][0]["verdict"] = "refutes"
    d["decision"]["verdict"] = "size"
    p = Payload.model_validate(d)
    errs = validate(p)
    assert any("refuted" in e for e in errs)


# ---------- verdict band + sizing ----------

def test_band_unproven_source_cannot_size():
    d = fixture_dict()
    d["decision"]["verdict"] = "size"  # fixture source is unproven
    p = Payload.model_validate(d)
    assert any("exceeds band" in e for e in validate(p))


def test_band_low_conviction_cannot_starter():
    d = fixture_dict()
    d["priced_in"]["gap_score"] = 0.1  # conviction 0.5*1*0.1*1 = 0.05 < 0.15
    p = Payload.model_validate(d)
    assert any("exceeds band" in e for e in validate(p))


def test_wait_and_pass_carry_zero_size():
    d = fixture_dict()
    d["decision"]["verdict"] = "wait"
    p = Payload.model_validate(d)
    assert validate(p) == []
    assert p.decision.size_frac == 0.0


def test_downgrade_is_always_allowed():
    d = fixture_dict()
    d["decision"]["verdict"] = "pass"
    p = Payload.model_validate(d)
    assert validate(p) == []  # more cautious than the band: fine


# ---------- expectations math ----------

def test_implied_cagr_hand_computed():
    # ev = 100*1e9 + 10e9 = 110e9; (110e9*1.1^5 / (20*4e9))^(1/5)-1 = 17.23%
    g = expectations.implied_cagr(100.0, 1e9, 10e9, 4e9, 20.0, years=5, discount=0.10)
    assert g == pytest.approx(0.1723, abs=2e-4)


# ---------- loop math ----------

def test_wilson_bounds():
    assert trackrecord.wilson(0, 0) == (0.0, 1.0)
    lo, hi = trackrecord.wilson(5, 5)
    assert lo > 0.5 and hi <= 1.0
    lo46, _ = trackrecord.wilson(4, 6)
    assert lo46 <= 0.5  # 4/6 not yet trustworthy


def _write_calls(path, rows):
    import csv
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=trackrecord.COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _row(i, verdict="starter", direction="long"):
    return {
        "run_id": f"r{i}", "source_id": "s", "published_at": "2026-05-01T12:00:00+00:00",
        "created_at": "2026-05-01T12:00:00+00:00", "ticker": f"T{i}", "direction": direction,
        "horizon_sessions": 10, "verdict": verdict, "conviction": 0.3, "size_frac": 0.03,
        "benchmark": "SPY",
    }


def test_score_source_status_and_discrimination(tmp_path, monkeypatch):
    calls = tmp_path / "calls.csv"
    rows = [_row(i, verdict=("starter" if i < 5 else "pass")) for i in range(8)]
    _write_calls(calls, rows)
    monkeypatch.setattr(trackrecord, "CALLS", calls)
    # acted (r0-r4) all win +2%; declined (r5-r7) all would have lost -1%
    excess = {f"T{i}": (0.02 if i < 5 else -0.01) for i in range(8)}
    monkeypatch.setattr(
        trackrecord.marketdata, "forward_excess",
        lambda ticker, pub, h, benchmark="SPY": excess[ticker],
    )
    s = trackrecord.score_source("s")
    assert s["n_calls"] == 8
    assert s["hit_rate"] == pytest.approx(5 / 8)
    assert s["discrimination"] == pytest.approx(0.03)  # +2% acted vs -1% declined
    # 5/8 hits but avg_excess>0 and lo<=0.5 -> provisional, not trusted
    assert s["status"] == "provisional"


def test_trusted_needs_magnitude_not_just_hits(tmp_path, monkeypatch):
    calls = tmp_path / "calls.csv"
    _write_calls(calls, [_row(i) for i in range(6)])
    monkeypatch.setattr(trackrecord, "CALLS", calls)
    # 6/6 small wins except one catastrophic loss would flip avg negative…
    # here: 6 hits, avg positive -> trusted
    monkeypatch.setattr(
        trackrecord.marketdata, "forward_excess",
        lambda ticker, pub, h, benchmark="SPY": 0.02,
    )
    assert trackrecord.score_source("s")["status"] == "trusted"
    # …now same hit pattern but magnitude-negative via one -30% blowup on a "hit rate" of 5/6
    vals = {f"T{i}": 0.02 for i in range(5)} | {"T5": -0.30}
    monkeypatch.setattr(
        trackrecord.marketdata, "forward_excess",
        lambda ticker, pub, h, benchmark="SPY": vals[ticker],
    )
    s = trackrecord.score_source("s")
    assert s["hit_rate"] == pytest.approx(5 / 6, abs=1e-3)  # stored rounded to 3dp
    assert s["avg_excess"] < 0
    assert s["status"] == "provisional"  # frequency without magnitude never promotes


def test_append_call_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(trackrecord, "CALLS", tmp_path / "calls.csv")
    p = load_fixture()
    validate(p)  # attach conviction
    assert trackrecord.append_call(p) is True
    assert trackrecord.append_call(p) is False  # no duplicate rows
    assert len(trackrecord._rows()) == 1


# ---------- entry-timing / leakage guard ----------

def _fake_yf_download(prices_by_date, tickers):
    idx = pd.DatetimeIndex(sorted(prices_by_date))
    df = pd.DataFrame(
        {t: [prices_by_date[d][j] for d in sorted(prices_by_date)] for j, t in enumerate(tickers)},
        index=idx,
    )
    return pd.concat({"Close": df}, axis=1)


def test_forward_excess_enters_after_publish_and_guards_maturity(monkeypatch):
    # publish Wed 2026-06-10 14:00 UTC; sessions 06-08..06-19
    days = pd.bdate_range("2026-06-08", "2026-06-19")
    # ticker doubles the benchmark's daily move so excess is unmistakable
    prices = {d: (100 + 2 * i, 100 + i) for i, d in enumerate(days)}
    fake = _fake_yf_download(prices, ["AAA", "SPY"])
    monkeypatch.setattr(marketdata.yf, "download", lambda *a, **k: fake)
    pub = dt.datetime(2026, 6, 10, 14, 0, tzinfo=dt.timezone.utc)

    x = marketdata.forward_excess("AAA", pub, 3)
    # entry must be 06-11 (first session AFTER publish date), exit 3 sessions later (06-16)
    # AAA: 106->112 (+5.660%); SPY: 103->106 (+2.913%); excess = +2.748%
    assert x == pytest.approx(112 / 106 - 106 / 103, abs=1e-9)
    # if it had leaked the publish-day close (104/102 entry) the number would differ
    assert x != pytest.approx(112 / 104 - 106 / 102, abs=1e-6)

    assert marketdata.forward_excess("AAA", pub, 10) is None  # not matured
    with pytest.raises(ValueError):
        marketdata.forward_excess("SPY", pub, 3)  # ticker == benchmark


def test_max_verdict_floors():
    p = load_fixture()
    validate(p)
    assert conviction.max_verdict(p) == "starter"  # 0.30, unproven
    p.source.track_record.status = "provisional"
    p.decision.conviction = 0.40
    assert conviction.max_verdict(p) == "size"
    p.decision.conviction = 0.10
    assert conviction.max_verdict(p) == "wait"
