# Where an edge can come from (2026-11-26)

Research notes, not betting advice. Everything here is tested on paper first.

## Why the last four rounds found nothing

Every test so far bet against the **sportsbook closing line** using **public box-score and line data**. The closing line is the most efficient price in sports, set after sharp money has hit it. Anyone with the same public data finds the same patterns, and those patterns get priced out. That is what the shuffle test and holdout showed: patterns existed in old seasons and faded.

To win, at least one of these must be true:

1. **A softer price**: you trade against a less efficient venue than the closing line.
2. **Something to sell**: you get paid for providing liquidity or taking a risk others avoid.
3. **Better or faster information** than the price reflects.
4. **A structural constraint**: two prices that must agree and don't.

## Strategies by source, ranked by what we can test

| #   | Strategy                                                                                                                                                                                                                                                                                    | Source            | Data needed                                                                          | Status                                                      |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| 1   | **Kalshi calibration (long shots vs favorites).** Studies of prediction markets find long shots overpriced and favorites underpriced, and takers losing more than makers. If Kalshi's sports and crypto contracts show this, buy favorites / sell long shots in the buckets that beat fees. | Softer price      | Kalshi settled markets + price history (public API, reachable only from Carson's PC) | Running                                                     |
| 2   | **Kalshi vs sportsbook consensus.** Use the de-vigged consensus of several books as the fair price and act only when Kalshi is off by more than fees. This uses the sharp market as the model instead of trying to beat it.                                                                 | Softer price      | Live Kalshi prices + a live odds feed                                                | Needs an odds API key from Carson                           |
| 3   | **Maker, not taker.** Post resting limit orders inside the spread on Kalshi and earn the spread; makers pay lower or no fees. Edge = spread captured minus losses to better-informed takers.                                                                                                | Something to sell | Kalshi order book history                                                            | Paper-only design; would need order placement, which is off |
| 4   | **Bracket consistency.** Kalshi crypto and totals markets come in ladders ("BTC above X" for many X). Prices must fall as X rises and adjacent brackets must add up. Violations after fees are near-riskless.                                                                               | Structural        | Kalshi snapshots of whole ladders                                                    | Can be checked from the same pull as #1                     |
| 5   | **Crypto funding/basis carry.** Hold spot and short the perpetual; collect funding when longs pay shorts. Market-neutral, paid for providing leverage.                                                                                                                                      | Something to sell | Funding-rate history                                                                 | Exchange APIs blocked from cloud; try PC                    |
| 6   | **News speed.** Injury and lineup news moves prices; a feed that reacts in seconds can trade Kalshi before it updates.                                                                                                                                                                      | Information       | Real-time news + Kalshi stream                                                       | Later; infrastructure heavy                                 |
| 7   | **Thin markets.** College basketball, small conferences, player props: fewer sharps, softer lines. Our own model can only beat prices that aren't already sharp.                                                                                                                            | Softer price      | Line history for those markets (none public found yet)                               | Blocked on data                                             |

## Order of work

1. Kalshi calibration (#1) and ladder consistency (#4) from Carson's PC.
2. If #1 shows a fee-beating bucket on a later-dated half of the data, paper-track it in the terminal.
3. Kalshi vs consensus (#2) once an odds feed key is available.
