# Priced-in procedure (expectations investing, mechanised)

The most important question the tweet skipped: what does the current price
already require? A correct, consensus thesis with no expectations gap is not a
trade.

## 1. Collect cited inputs

Gather into `priced_in.inputs[]` (each a `SourceRef` with evidence):

- current price and shares outstanding (or market cap), net debt
- a base cash-flow / earnings level (last FY or NTM FCF, EBITDA, or EPS)
- a defensible exit multiple (sector median, the company's own history)

Every number carries a verbatim quote + url. The technicals snapshot from
`cli technicals` gives you price context; fundamental inputs come from filings
or IR (see verification.md for what counts as primary).

## 2. Run the math in code

`python -m ledger.cli imply --price P --shares S --net-debt D --fcf F --multiple M [--years 5 --discount 0.10]`

This prints the FCF CAGR the price implies. Quote its output verbatim in
`expectations_summary`. You interpret; you never compute.

## 3. Compare to base rates

Outside view first: how often do companies of this size/sector actually deliver
the implied growth for that long? Use the reference class, not the story. If
implied growth sits in the top decile of historical outcomes, the bar is high
and `gap_score` should be low unless the variant view is specific and verified.

## 4. Set gap_score (0 = fully priced, 1 = clear gap)

- **0.8–1.0** — verified variant view; implied expectations undemanding vs base
  rates; market narrative contradicts primary evidence
- **0.5–0.7** — some gap, partially reflected; variant view plausible, not yet
  confirmed by primaries
- **0.2–0.4** — thesis mostly consensus; implied growth demanding but arguable
- **0.0–0.1** — thesis is the consensus; implied expectations at/above base-rate
  ceilings; nothing variant survives verification

## 5. Set narrative_stage

Use the technicals snapshot + coverage judgment:

- **early** — narrative not in mainstream coverage; price not extended
  (within ~1 ATR of the 50DMA; RSI < ~65; 3-month return unexceptional)
- **crowding** — narrative in every feed; price extended above the 50DMA;
  RSI 65–75; late-comer articles appearing
- **exhausted** — parabolic/extended (RSI > ~75, far above 200DMA), thesis is
  a magazine cover, or the catalyst has already printed

When torn between two stages, pick the later one (conservative).
