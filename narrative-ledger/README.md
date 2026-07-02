# narrative-ledger

A skill-driven accountability engine for borrowed macro/thematic theses.
Deterministic Python owns feeds, market data, the expectations math, scoring,
validation and rendering; the reasoning agent owns extraction, verification and
judgment; a versioned JSON payload is the only interface between them, and an
outcome loop re-scores every source on realised, benchmark-relative returns.

Built from `../plan_build_v1.html` (v1.1), which is derived from
`../research_review.html`. Read those for the why; this README is the how.

## Run a report

```bash
cd narrative-ledger
python -m ledger.cli ingest --source citrini     # latest post -> runs/<date>_citrini/
python -m ledger.cli new    --source citrini     # scaffold payload.json + source score
# ... agent fills payload.json per SKILL.md (claims -> verify -> priced_in -> decision),
#     calling `technicals` and `imply` along the way ...
python -m ledger.cli validate runs/<date>_citrini   # the gate; on pass, code logs the call
python -m ledger.cli render   runs/<date>_citrini   # decision-first report.html
```

Later, when the call matures (T + horizon_sessions):

```bash
python -m ledger.cli outcome runs/<date>_citrini    # realised excess; re-scores the source
python -m ledger.cli score                          # per-source weight/status/discrimination
python -m ledger.cli watch                          # open calls + kill-switch dates due
```

## Conventions that keep the ledger honest

- **Entry timing**: outcomes enter at the first close on a session *after* the
  publish date — a source never gets credit for a close that predates its post.
- **Horizons are trading sessions**, pre-committed at entry (default 10).
- **Every verdict is logged**, `wait`/`pass` included, and shadow-scored: the
  `discrimination` stat = mean(acted excess) − mean(declined excess) grades the
  gate itself against blindly following the feed.
- **Survivorship**: only calls logged on their public date, after tracking
  began, enter the file. `runs/` and `ledger/calls.csv` are committed to git —
  history is the tamper-evident append-only guarantee.
- **First-run caveat**: a first run on an older post is selected by recency,
  but any verdict formed after the fact can see what prices did since publish.
  Honest datapoints accrue from calls logged on (or near) their publish date
  going forward; treat backfilled outcomes as demo data, not evidence.
- **Only code writes `ledger/calls.csv`** (append-only, idempotent by run_id).
  The agent never touches the ledger, `conviction`, `size_frac`, or `outcome`.

## Skill install

`SKILL.md` + `references/` are the agent's half. Point your agent runtime at the
repo (run in-repo), or copy/symlink the folder into your skills directory.

## Watchlist maintenance

`config/watchlist.yaml`. Kinds: `rss` (WordPress + Substack; set
`fetch_full: true` for excerpt-only feeds — Lyn Alden's is), `bluesky`
(unauthenticated public AppView, no credentials), `manual` (X: paste into
`runs/<date>_<id>/artifact.md` + write `sources.json`).

Tier/status is **computed** from outcomes, never hand-set.

## Tests

```bash
python -m pytest tests/ -q
```

Firewall rules (plan §01 ①–⑥), the verdict band, sizing caps, Wilson/shrink
math, shadow-scoring, entry-timing leakage guard, and `implied_cagr` are all
unit-tested.

---

Research process, not investment advice.
