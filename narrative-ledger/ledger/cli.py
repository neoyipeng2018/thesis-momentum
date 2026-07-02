"""Orchestrator (plan §5.7). The agent calls these between its cognitive steps.

ingest | new | technicals | imply | validate | render | outcome | score | watch

The ledger write lives inside the validate-pass path, in code, never in the
agent's hands (firewall 5).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

from . import expectations, ingest, marketdata, render, trackrecord, validate as validate_mod
from .models import Payload

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"


def _latest_run_dir(source_id: str) -> pathlib.Path:
    dirs = sorted(RUNS.glob(f"*_{source_id}"))
    if not dirs:
        raise SystemExit(f"no runs for '{source_id}' — run `ingest --source {source_id}` first")
    return dirs[-1]


def _load_payload(run: str) -> tuple[Payload, pathlib.Path]:
    run_dir = pathlib.Path(run)
    if not run_dir.exists():
        run_dir = ROOT / run
    f = run_dir / "payload.json"
    if not f.exists():
        raise SystemExit(f"{f} not found")
    return Payload.model_validate_json(f.read_text()), run_dir


def scaffold(source_id: str) -> None:
    run_dir = _latest_run_dir(source_id)
    src_meta = json.loads((run_dir / "sources.json").read_text())
    wl = ingest.load_watchlist()
    defaults = wl["defaults"]
    tr = trackrecord.track_record_for(source_id)
    payload = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {
            "id": source_id,
            "name": src_meta.get("source_name", source_id),
            "venue": src_meta.get("venue"),
            "artifact_url": src_meta["artifact_url"],
            "published_at": src_meta["published_at"],
            "track_record": tr.model_dump(),
        },
        "claims": [],
        "priced_in": {
            "ticker": "",
            "expectations_summary": "",
            "variant_view": "",
            "inputs": [],
            "gap_score": 0.0,
            "narrative_stage": "early",
        },
        "decision": {
            "verdict": "wait",
            "ticker": "",
            "direction": "long",
            "horizon_sessions": defaults.get("horizon_sessions", 10),
            "kill_switches": [],
            "conviction": None,
            "size_frac": None,
        },
        "outcome": {},
        "forecast": None,
    }
    out = run_dir / "payload.json"
    if out.exists():
        raise SystemExit(f"{out} already exists — refusing to overwrite a run")
    out.write_text(json.dumps(payload, indent=2))
    print(f"scaffolded -> {out.relative_to(ROOT)}")
    print(f"source score: weight={tr.source_weight} status={tr.status} "
          f"(n_matured={tr.n_calls})")
    print("next: agent fills claims / priced_in / decision per SKILL.md, "
          "then `validate`, then `render`")


def main() -> None:
    ap = argparse.ArgumentParser(prog="ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest", help="pull latest post -> runs/<date>_<id>/")
    s.add_argument("--source", required=True)
    s = sub.add_parser("new", help="scaffold payload.json (+ source score)")
    s.add_argument("--source", required=True)
    s = sub.add_parser("technicals", help="stage/extension read for the extracted ticker")
    s.add_argument("run")
    s.add_argument("--ticker", required=True)
    s = sub.add_parser("imply", help="reverse-DCF: implied FCF CAGR from cited inputs")
    s.add_argument("--price", type=float, required=True)
    s.add_argument("--shares", type=float, required=True, help="shares outstanding")
    s.add_argument("--net-debt", type=float, default=0.0)
    s.add_argument("--fcf", type=float, required=True, help="base FCF (same units as price*shares)")
    s.add_argument("--multiple", type=float, required=True, help="exit EV/FCF multiple")
    s.add_argument("--years", type=int, default=5)
    s.add_argument("--discount", type=float, default=0.10)
    for name in ("validate", "render"):
        sub.add_parser(name).add_argument("run")
    s = sub.add_parser("outcome", help="close a matured call and re-score the source")
    s.add_argument("run")
    s.add_argument("--kill-switch", default=None, help="condition text if a kill-switch forced the exit")
    sub.add_parser("score", help="per-source table incl. discrimination")
    sub.add_parser("watch", help="open calls + kill-switch dates coming due")
    a = ap.parse_args()

    if a.cmd == "ingest":
        ingest.run(a.source)
    elif a.cmd == "new":
        scaffold(a.source)
    elif a.cmd == "technicals":
        t = marketdata.technicals(a.ticker)
        run_dir = pathlib.Path(a.run)
        (run_dir / "technicals.json").write_text(json.dumps(t, indent=2))  # provenance
        print(json.dumps(t, indent=2))
    elif a.cmd == "imply":
        g = expectations.implied_cagr(
            a.price, a.shares, a.net_debt, a.fcf, a.multiple, a.years, a.discount
        )
        print(
            expectations.describe(
                g, price=a.price, shares=a.shares, net_debt=a.net_debt,
                fcf=a.fcf, exit_multiple=a.multiple, years=a.years, discount=a.discount,
            )
        )
    elif a.cmd == "validate":
        p, run_dir = _load_payload(a.run)
        errs = validate_mod.validate(p)  # computes conviction + band inside
        if errs:
            print("GATE FAILED:")
            print("\n".join(f"  - {e}" for e in errs))
            raise SystemExit(1)
        (run_dir / "payload.json").write_text(p.model_dump_json(indent=2))
        wrote = trackrecord.append_call(p)  # CODE writes calls.csv — firewall 5
        print("OK — payload passes the gate")
        print(f"conviction={p.decision.conviction} size_frac={p.decision.size_frac} "
              f"verdict={p.decision.verdict}")
        print("call logged to ledger/calls.csv" if wrote else "call already logged (idempotent)")
    elif a.cmd == "render":
        p, run_dir = _load_payload(a.run)
        out = run_dir / "report.html"
        render.render(p, out)
        print(f"report -> {out}")
    elif a.cmd == "outcome":
        trackrecord.close_and_rescore(a.run, a.kill_switch)
    elif a.cmd == "score":
        rows = trackrecord._rows()
        ids = sorted({r["source_id"] for r in rows})
        if not ids:
            print("no calls logged yet")
        for i in ids:
            s = trackrecord.score_source(i)
            print(json.dumps(s))
    elif a.cmd == "watch":
        calls = trackrecord.open_calls()
        if not calls:
            print("no open calls")
        for c in calls:
            print(f"{c['run_id']}: {c['verdict']} {c['direction']} {c['ticker']} "
                  f"(published {c['published_at']}, horizon {c['horizon_sessions']} sess)")
            for k in c["kill_switches"]:
                print(f"    kill-switch: {k}")


if __name__ == "__main__":
    main()
