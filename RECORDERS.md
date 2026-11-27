# Forward recorders: pre-registered pass bars

Written 2026-11-27, before any recorded data exists. These rules do not change after data arrives.
If a rule turns out to be unworkable, the strategy fails and a new, separately registered test starts.

Recording: `kil_capital/research/recorder.py`, every dashboard run (~2.5 min), no orders, no keys.
Data: `data/recorders/<UTC day>/*.jsonl.gz` on the `state` branch (quotes, tape, books, settle, fees, incentives).
Window: starts with the first run after 2026-11-27. Earliest report 2026-12-11 (2 weeks), latest 2026-12-25 (4 weeks).

## Common rules (every strategy)

- **Fills (maker strategies).** A hypothetical quote joins the best price at the moment it is placed, behind
  everything already resting there (queue size from the `books` snapshot; with no snapshot, the queue is set to 2x the median recorded
  queue for that price band). It fills only when the `tape` shows takers trading at or through that price with
  cumulative size greater than the queue ahead. Partial fills count pro rata.
- **Fillers are assumed informed.** Every fill is held to settlement; no exits, no hedges.
- **Fees.** Exact Kalshi fees per series from the `fees` stream: taker 0.07 x C x P x (1-P), maker
  0.0175 x C x P x (1-P) only where the series fee type includes maker fees, each rounded up to the cent per order,
  times the series fee multiplier. The constants are checked against Kalshi's published fee schedule before
  the report; if they differ, Kalshi's schedule wins.
- **Unit.** One order of 10 contracts per qualifying market (one per market, first qualifying moment only).
- **Pass bar (all must hold):**
  1. At least 200 filled orders across at least 50 distinct events.
  2. Mean net return per dollar risked > 0 after fees.
  3. Lower confidence bound > 0: one-sided 97.5% bound (90% family-wise across the four tests, Bonferroni),
     event-clustered bootstrap, 10,000 resamples.
  4. Positive mean in both the first 60% and the last 40% of calendar days (the last 40% is the holdout).
  5. Still non-negative with the queue ahead doubled (fill realism).
- **Early kill.** After 7 days, if the 90% upper bound of mean net return is below 0, the strategy is dropped.
- **No tuning.** Thresholds below are fixed. Variants are new tests and count toward multiple testing.

## The four tests

**T1. Sell longshots (<=10c).** When a market's YES or NO ask is <= 10c and closes within 24h, offer that
longshot side at its current best ask (sell the longshot, i.e. buy the other side as maker). P&L per contract:
price received minus 1 if the longshot wins, minus maker fee. Prior evidence: buyers of <=10c lost 38-59%
(taker-side history; whether a maker gets filled without being picked off is exactly what this tests).

**T2. Late favourites (>=85c).** In the last 6 hours before close, when a side's best bid is >= 85c, bid for
that favourite at its best bid. P&L: 1 if it wins minus price minus maker fee. Prior: +~2.5% over 235 events.
T1 and T2 overlap on 90c+/10c- markets; each is scored separately and the overlap is reported.

**T3. Liquidity rewards.** Quote both sides at the tightest spread and size the program requires, on every
rewarded market. P&L: reward accrued under the program's published terms minus fill losses held to settlement.
Prior: ~0.42%/day before fill losses. If program terms cannot be read from Kalshi (`incentives` stream says
unavailable), T3 is reported as "cannot test", never as a pass.

**T4. Fade BTC/ETH hourly spikes (watch list).** Spike: a 20c+ move in the trade price of one KXBTCD/KXETHD
market within 60 seconds. Fade: take the opposite side at the first trade at least 5 seconds after the spike is
complete, pay the taker fee, hold to settlement. Prior: positive in both halves but only 6 days of data.

## Not in this round

NFL unders in high forecast wind: needs a forecast-wind (not observed-wind) history test first; it has its own
sleeve in the paper Book at $10 and is graded there.

## Output

`RESEARCH_RECORDERS_REPORT.md` with, per test: fills, events, fill rate, mean net return, both halves, the
97.5% lower bound, the doubled-queue result, filled-vs-unfilled comparison (adverse selection), and a plain
PASS / FAIL / CANNOT TEST. Only a PASS goes to a live spec, and nothing goes live until Carson has seen the
backtest and the forward result for that strategy and typed a confirmation.
