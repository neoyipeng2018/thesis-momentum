# Decision procedure

## 0. Pre-mortem FIRST (Klein)

Before writing the verdict: assume it is T+horizon and the trade failed
badly. Write 3–5 concrete reasons why. Then write the bear steelman — the best
case a smart short would make today. The kill-switches must cover the
pre-mortem's top reasons; if you can't convert a failure reason into a
measurable, dated condition, that reason argues for `wait`.

## 1. The verdict ladder

- **size** — full conviction expression, sized by code
- **starter** — real but partial; position opens small, earns adds via outcomes
- **wait** — thesis alive, entry wrong (stage/extension/pending catalyst);
  logged and shadow-scored, re-examine at a dated trigger
- **pass** — thesis broken (refuted spine, no expectations gap, exhausted);
  logged and shadow-scored — a good pass is alpha too

Code computes conviction = source_weight × verification rate × gap × stage and
enforces a band: conviction ≥ 0.35 permits `size` (never for unproven sources),
≥ 0.15 permits `starter`. You may always choose a MORE cautious verdict than
the band allows — say why in `variant_view` or the kill-switches — never bolder.

## 2. Horizon

`horizon_sessions`, pre-committed at entry, in TRADING sessions. Default 10
(the thematic edge lives there). Catalyst-driven claims may pre-commit to the
catalyst date instead: horizon = sessions to catalyst + 2. Do not grade a
10-session thesis at 1 session; do not let a 10-session thesis drift into a
"long-term hold" after it goes red.

## 3. Kill-switches (≥3, measurable + dated)

Each has a `condition` a stranger could adjudicate and a `by_date`:

- BAD: "sentiment deteriorates", "thesis weakens"
- GOOD: "2026-08-15: reported Q2 gross margin < 38%", "2026-07-31: no CMS
  final rule published", "close < 200DMA for 3 consecutive sessions"

At least one kill-switch should map to the spine claim (if the load-bearing
fact breaks, you exit), and at least one to price action (invalidation level).

## 4. What you must leave null

`conviction`, `size_frac`, `outcome`, `forecast`. Code fills the first two at
validate; outcome closes at T+horizon; forecast stays null forever (firewall).
