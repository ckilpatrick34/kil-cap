# Kil Capital Terminal

A local Kalshi research terminal for Carson. It runs only on your Mac at `http://127.0.0.1:8000` (set
`KIL_PORT` to change it). Nothing listens on the network and there is no cloud part.

**It only recommends bets.** It never connects to your Kalshi account, holds no API keys, and has no code
that places, amends or cancels orders. It reads Kalshi's free public market data, ESPN scores and schedules,
and weather. The autopilot trades **paper money only** and is always OFF when the app starts.

## Run it

Double-click `start.command`. It finds Python 3.12+, makes `.venv`, installs `requirements.txt`, starts the
server and opens the browser. Or: `python -m kil_capital.api.app`.

## What you see

- **Game picks** (NFL, NBA, NHL, college football and basketball): winner, spread and total markets. Each pick
  shows our fair price, the edge after Kalshi's fee, a confidence grade, ROI, the Kelly stake and the expected
  profit. Picks are **ranked by expected profit in dollars**.
- **Crypto desk**: volatility-based fair prices on Kalshi crypto contracts, plus the trend-following lab.
- **Live markets**: the most-traded Kalshi markets; click one for its order book.
- **Paper portfolio / Autopilot**: a $1,000 pretend balance with live P&L. Buys fill at the ask, sells at the
  bid, with the taker fee.
- **Track record**: every pick is logged before the game at the price we'd have paid, then graded when Kalshi
  settles it, with closing-line value.
- Mississippi State is hard-blocked everywhere (Michigan State and Missouri State are allowed).

## How a pick is priced

1. **Our own ratings** from this season's results only (ridge/Massey margins, offence/defence for totals),
   recent games weighted more, with rest, injuries and weather adjustments. Sportsbook lines are _not_ used
   to build these.
2. **Blend** with the de-vigged sportsbook line, which is sharp; `w_model` per league sets how much we trust
   ourselves.
3. **Shrink** toward reality: once a league × market × edge bucket has graded picks, its fair price is pulled
   toward what that bucket actually hit.
4. **Gates**: edge after fee ≥ minimum (more for pro leagues, spreads and totals), model and book agree, price
   between 15¢ and 92¢, game not started.

## Sizing: built for max profit

- Quarter-Kelly on the fee-inclusive cost: `f = (fair − cost) / (1 − cost)`, stake = `0.25 × f × equity`,
  capped by the autopilot's max per trade. Full Kelly is too aggressive when fair prices carry model error.
- Times a **segment multiplier** from `data/segments.json`, built from Big Vin's graded history plus our own:
  ROI per league × market × edge bucket × favourite/underdog, shrunk toward 0 (150 pseudo-picks). A segment
  with shrunk ROI ≤ −3% is skipped; others get 0.5× to 1.5×.
- Expected profit = contracts × (fair − cost). ROI = (fair − cost) / cost.

## Self-learning loop (nightly, after 4 AM Central)

`kil_capital/sports/learn.py` retrains every league on settled games and **only promotes a new model if it
beats the current one on games it never saw**:

- Predictions are walk-forward: each week's games are predicted from ratings fitted only on earlier games.
- Candidate settings (home edge, recency half-life, ridge strength) are tuned on an earlier window.
- Champion and challenger are compared on the last 21 days, which tuning never touched. The challenger wins
  only if it lowers log loss by 0.002+ on 40+ games. Sigmas and the model-vs-book blend weight are then
  re-fitted on those unseen games.
- Champions are saved in `data/model_params.json`; every run is logged in `data/learn_log.json`.
  `GET /api/learn` shows both plus the segment table.

## Big Vin: learn from its wins, explain its losses (run on your Mac)

```
python -m kil_capital.research.bigvin data/bigvin
```

Reads Big Vin's cached history, writes `data/bigvin_picks.json` (folded into the segment table each night) and
`reports/BIG_VIN_LEARNING.md`: results by league, bet type, edge size, favourite/underdog, price band, line
movement and confidence rank; the main reasons it loses; and the **60% win-rate search**. That search picks
segments on the first 70% of picks and judges them on the last 30%, showing win rate **and** ROI, because a
70% winner at 80¢ still loses money. A segment counts only if it holds 60%+ and is profitable out of sample.

## Deep model: more data, judged on unseen seasons

```
python -m kil_capital.research.deep --league nfl
```

Downloads nflverse's public file of every NFL game since 1999 (closing spread and total, rest, roof,
weather, starting QBs), compresses each team's history into point-in-time features (Elo, fast/slow
form, points for/against, how often it beat the closing line, QB changes), and trains gradient-boosted
and ridge models on the *market's error*. Each season is predicted by a model trained only on earlier
seasons; bet thresholds are chosen on 2006-2015 and only reported on 2016 onward. A model is promoted
only if it beats the closing line's error on those unseen seasons and is profitable at -110. Results:
`reports/DEEP_NFL.md`, `data/deep_models.json`, and `GET /api/learn`.

## Backtests

```
source .venv/bin/activate
python -m kil_capital.backtest.fetch --days 365     # rebuild the cache (MSU markets dropped)
python -m kil_capital.backtest.run                  # reports/<id>.json + .md and SUMMARY.md
```

## Tests

```
python -m pytest
```

Covers recommend-only (no order, kill or go-live routes, no venue), the MSU blocklist both ways, paper math and
autopilot limits, the API security guards (token, host and origin checks), the hash-chained audit, fees, the
models, the track record, the deep model (no leakage, no edge invented against an efficient market), the learning loop (no peeking, promotion only on unseen games), Kelly sizing and the
segment table, and the Big Vin column mapping.

## Layout

```
kil_capital/
  config.py               settings, RiskLimits (tighten-only at runtime)
  core/   paper.py        paper book + autopilot (off at start)
          blocklist.py    hard Mississippi State block (no off switch)
          ledger.py       SQLite ledger + append-only hash-chained audit
          risk.py money.py orders.py desks.py   limits, fees, types (used by paper + backtests)
  venue/  public.py       read-only public Kalshi API (2 req/s, cached, backoff)
  sports/ ratings.py model.py slate.py track.py   game model, pricing, picks, track record
          learn.py        nightly retrain, champion/challenger on unseen games
          segments.py     segment table, Kelly sizing, 60% search
  crypto/                 crypto desk and trend lab
  research/bigvin.py      Big Vin loss analysis and learning
          history.py features.py deep.py   multi-season data, point-in-time features, walk-forward models
  strategies/ backtest/   research strategies and the backtester
  api/    app.py terminal.py   FastAPI app + background loops
  web/                    dashboard (no build step)
tests/
start.command
```
