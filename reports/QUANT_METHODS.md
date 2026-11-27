# Hedge-fund methods on sports prices (2026-11-27)

Recommend-only research. Every number below is scored on seasons the method never saw.

## Bottom line

* **No new money-making rule passed.** 23 obscure-stat rules (referees, stadiums, altitude, travel, letdown, lookahead, overtime hangover, dome teams in the cold, revenge, NBA/NHL schedule spots) and 6 moneyline-vs-spread relative-value trades: none cleared the bar on unseen seasons. Closest: NFL moneyline vs spread at a 3% gap (+3.9% then +8.9% return, test z 1.2), too weak to bet.
* **Fair value is already right.** All four de-vig methods score within 0.001 log loss of each other, and sportsbook closing lines show no favourite-longshot bias. The plain (multiplicative) de-vig the app uses is fine.
* **Black-Scholes N(d2) misprices NFL spread ladders near key numbers by 6-9 cents** (home -3: 'wins by 4+' is 41.7% in reality, 48.5% by N(d2)). A histogram of past games at the same spread fixes it. This is the pricing tool for Kalshi spread ladders, and the place to look for Kalshi mispricing once Kalshi history is pulled.
* **The simple live model is not good enough to trade NFL in-game.** Score + clock + possession N(d2) loses clearly to a full win-probability model, worst in the last 10 minutes, the time live prices move most.
* **Sizing: bet $3-5, not $10, on the current NFL sleeves.** With honest uncertainty about the edge, full Kelly is 1-4% of a $100 bankroll. Flat $10 gives a 20-36% chance of being down half at some point in one season; $5 cuts that to 1-7% and still gains in the median season. Same-Sunday bets are close to independent.
* **Kalshi itself is the untested frontier.** A 2025 study of Kalshi (Burgi, Deng and Whelan, 'Makers and Takers') reports a favourite-longshot bias on Kalshi and that resting (maker) orders do better than market (taker) orders. Testing that on sports contracts, the Kalshi vs sportsbook gap, and ladder mispricing needs Kalshi price history, which only downloads from Carson's computer: `python -m kil_capital.backtest.fetch --series KXNFLGAME,KXNBAGAME,KXNHLGAME --days 365`.
* **Fees:** Kalshi's taker fee is 0.07 x P x (1 - P), about 1.75 cents on a 50-cent contract, so a coin-flip bet breaks even at about 51.8% versus 52.4% at -110. Kalshi is a cheaper venue than a -110 book for the same edge, when it lists a matching line.

## A. Fair value: removing the bookmaker margin

A Kalshi contract is a probability, so the fair price of a game is the sportsbook price with the bookmaker's margin taken out. There are four standard ways to take it out. They differ most on long shots. Scored on closing moneylines in the test seasons (2017 on). Lower log loss is better.

| League | Test games | Multiplicative | Additive | Power | Shin | Shin + recalibration |
|---|---|---|---|---|---|---|
| NFL | 2,650 | 0.6077 | 0.6074 | 0.6074 | 0.6074 | **0.6073** |
| NBA | 6,256 | **0.6047** | 0.6054 | 0.6062 | 0.6054 | 0.6047 |
| NHL | 6,186 | 0.6653 | 0.6653 | 0.6653 | 0.6653 | **0.6652** |
| MLB | 2,948 | 0.6821 | 0.6823 | 0.6825 | 0.6823 | **0.6816** |

Favourite-longshot check (test seasons, both sides of every game, multiplicative de-vig):

| League | Fair-price bucket | Sides | Average fair price | Actually won | Gap |
|---|---|---|---|---|---|
| NFL | 0%-25% | 577 | 19.1% | 18.2% | -0.9% |
| NFL | 25%-40% | 1,231 | 32.9% | 32.9% | -0.0% |
| NFL | 40%-60% | 1,684 | 50.0% | 50.0% | +0.0% |
| NFL | 60%-75% | 1,231 | 67.1% | 67.1% | +0.0% |
| NFL | 75%-100% | 577 | 80.9% | 81.8% | +0.9% |
| NBA | 0%-25% | 1,702 | 17.3% | 18.4% | +1.1% |
| NBA | 25%-40% | 2,718 | 32.9% | 32.7% | -0.2% |
| NBA | 40%-60% | 3,672 | 50.0% | 50.0% | +0.0% |
| NBA | 60%-75% | 2,718 | 67.1% | 67.3% | +0.2% |
| NBA | 75%-100% | 1,702 | 82.7% | 81.6% | -1.1% |
| NHL | 0%-25% | 118 | 22.7% | 23.7% | +1.0% |
| NHL | 25%-40% | 2,314 | 35.1% | 34.1% | -1.0% |
| NHL | 40%-60% | 7,508 | 50.0% | 50.0% | +0.0% |
| NHL | 60%-75% | 2,314 | 64.9% | 65.9% | +1.0% |
| NHL | 75%-100% | 118 | 77.3% | 76.3% | -1.0% |
| MLB | 0%-25% | 2 | 24.4% | 0.0% | -24.4% |
| MLB | 25%-40% | 780 | 36.4% | 38.1% | +1.7% |
| MLB | 40%-60% | 4,329 | 50.0% | 50.0% | -0.0% |
| MLB | 60%-75% | 783 | 63.6% | 61.9% | -1.6% |
| MLB | 75%-100% | 2 | 75.6% | 100.0% | +24.4% |

## B. Black-Scholes digital pricing

A Kalshi game contract pays $1 if something happens, which makes it a digital option. Treat the final margin as the 'stock' with expected value = the sportsbook spread and volatility sigma. Then the fair price of 'home wins by more than k' is N(d2), with d2 = (spread - k) / sigma. This prices every rung of a Kalshi spread ladder from one sportsbook number.

* NFL sigma (fit on 2006-2016): **13.4 points**.
* Pricing every half-point strike within 14 points of the line for 2,550 test games (73,950 prices): normal N(d2) log loss 0.5641, shifted histogram 0.5632, histogram of past games at the same spread 0.5620 (lower is better).

Key numbers break the normal curve. Home favourite of exactly 3, test seasons:

| Strike: home wins by more than | Games | Actually | N(d2) price | Same-spread histogram |
|---|---|---|---|---|
| -3.5 | 204 | 72.5% | 68.6% | 69.6% |
| -2.5 | 204 | 65.2% | 65.9% | 62.1% |
| +2.5 | 204 | 53.9% | 51.5% | 52.4% |
| +3.5 | 204 | 41.7% | 48.5% | 42.6% |
| +6.5 | 204 | 33.3% | 39.7% | 35.5% |
| +7.5 | 204 | 27.9% | 36.8% | 30.9% |

Volatility of the final margin and the final total, discovery seasons:

| League | Margin sigma | Total sigma | Total sigma when total is low / mid / high |
|---|---|---|---|
| NFL | 13.4 | 13.49 | 13.54 (at 37.5) / 13.49 (at 42.5) / 13.45 (at 47) |
| NBA | 11.9 | 17.30 | 17.24 (at 190) / 16.91 (at 200.5) / 17.73 (at 211.5) |
| NHL | n/a | 2.18 | 1.61 (at 5) / 2.61 (at 5.5) / 2.21 (at 5.5) |
| MLB | n/a | 4.29 | 3.86 (at 7) / 4.54 (at 8) / 4.45 (at 9) |

### Moneyline vs spread relative value

The same book prices the moneyline and the spread. Through the margin distribution, the spread implies a win probability. When the moneyline's no-vig price disagrees with the spread's by more than a threshold, bet the moneyline side the spread says is cheap, at the real moneyline price. Thresholds were fixed before scoring.

| League | Gap | Discovery win / return / bets | Test win / return / bets | Test z |
|---|---|---|---|---|
| NFL | 2% | 37.4% / +4.0% / 1354 | 38.4% / +1.4% / 1070 | +0.3 |
| NFL | 3% | 35.7% / +3.9% / 630 | 39.2% / +8.9% / 452 | +1.2 |
| NFL | 5% | 40.6% / +33.4% / 32 | 43.2% / +28.6% / 37 | +1.1 |
| NBA | 2% | 31.0% / -2.0% / 2639 | 43.7% / +1.8% / 1578 | +0.4 |
| NBA | 3% | 20.2% / -0.6% / 1042 | 34.4% / -4.3% / 389 | -0.5 |
| NBA | 5% | 11.7% / -40.7% / 60 | 42.4% / +7.5% / 33 | +0.2 |

## C. Live pricing (in-game digital option)

In a live game the 'stock' is the current score margin plus the expected margin still to come, and the volatility shrinks with time left: P(home wins) = N((lead + spread x time left + possession value) / (sigma x sqrt(time left))). Fit on 2019-2021 plays, scored on 2022-2025 plays. The benchmark is nflverse's own win-probability model, which uses down, distance, field position and timeouts.

* Sigma fit on discovery plays: **17 points per game**.

| Model | All test plays | Last 10 minutes |
|---|---|---|
| Score + time only | 0.4896 | 0.3764 |
| + possession value (expected points) | 0.4813 | 0.3521 |
| nflverse win-probability model | 0.4602 | 0.2846 |

Plays scored: 46,509 test, 34,145 discovery (every 4th play).

## D. Sizing: Kelly with honest uncertainty, and correlation

* **Same-week correlation of NFL over/under results**: the spread of weekly over rates is 0.95x what independent games would give (1.00 = independent), an average pairwise correlation of about -0.004. Over/under bets on the same Sunday are close to independent, so no slate-level haircut is needed.
* **Home-cover results** are 0.98x (about independent).

One NFL season on a $100 bankroll, 2,000 simulated seasons. The true win rate is unknown: each simulated season draws it from a skeptical estimate that starts at break-even and moves toward the test record by how many bets that record holds (a 400-bet prior at 52.4%). Bets are -110.

| Rule | Test record | Skeptical win rate | Sizing | Median end | Chance of profit | Chance of losing half |
|---|---|---|---|---|---|---|
| NFL spread vs opener 3+ | 55.9% on 390 | 54.1% | Flat $10 | $109 | 61% | 31% |
| NFL spread vs opener 3+ | 55.9% on 390 | 54.1% | Flat $5 | $105 | 60% | 6% |
| NFL spread vs opener 3+ | 55.9% on 390 | 54.1% | Full Kelly (3.6% a bet) | $101 | 59% | 0% |
| NFL spread vs opener 3+ | 55.9% on 390 | 54.1% | Quarter Kelly (0.9% a bet) | $101 | 62% | 0% |
| NFL wind 15+ under | 55.4% on 267 | 53.6% | Flat $10 | $110 | 52% | 20% |
| NFL wind 15+ under | 55.4% on 267 | 53.6% | Flat $5 | $105 | 54% | 1% |
| NFL wind 15+ under | 55.4% on 267 | 53.6% | Full Kelly (2.5% a bet) | $102 | 54% | 0% |
| NFL wind 15+ under | 55.4% on 267 | 53.6% | Quarter Kelly (0.6% a bet) | $101 | 56% | 0% |
| NFL primetime under | 53.2% on 491 | 52.8% | Flat $10 | $102 | 56% | 36% |
| NFL primetime under | 53.2% on 491 | 52.8% | Flat $5 | $101 | 58% | 7% |
| NFL primetime under | 53.2% on 491 | 52.8% | Full Kelly (0.9% a bet) | $100 | 58% | 0% |
| NFL primetime under | 53.2% on 491 | 52.8% | Quarter Kelly (0.2% a bet) | $100 | 58% | 0% |

## E. Obscure stats and weird spots

Rules written before scoring. Referee, stadium and coach tendencies are walk-forward: each game uses only games already played. NFL discovery = 1999-2012, test = 2013 on. NBA/NHL discovery = 2011-2016, test = 2017 on. Graded at the listed price (else -110). **Pass** = profitable in both halves, 150+ test bets, test z 2+.

| Rule | Discovery win / return / bets | Test win / return / bets | Test z | Pass |
|---|---|---|---|---|
| NHL altitude: visitor on a back-to-back at Colorado, bet Colorado ML | 55.1% / -5.5% / 49 | 75.6% / +16.8% / 45 | +1.6 |  |
| Lookahead: 7+ point favourite with a primetime division game next, fade it ATS | 47.8% / -7.6% / 69 | 58.4% / +12.1% / 101 | +1.3 |  |
| Letdown: team won outright as a 7+ point dog last week, fade it ATS | 48.8% / -6.0% / 201 | 54.9% / +7.0% / 184 | +1.0 |  |
| Stadium over-rate 43% or less: bet under | 51.3% / -0.9% / 388 | 53.9% / +4.5% / 384 | +0.9 |  |
| Altitude: Denver at home, bet Denver ATS | 42.9% / -17.3% / 112 | 54.8% / +6.5% / 115 | +0.7 |  |
| Stadium over-rate 57%+ (past games): bet over | 52.1% / +0.6% / 292 | 53.8% / +4.0% / 225 | +0.6 |  |
| Referee over-rate 45% or less: bet under | 50.5% / -2.2% / 560 | 52.3% / +1.4% / 736 | +0.4 |  |
| Overtime hangover: played OT last week, fade it ATS | 49.1% / -4.7% / 389 | 52.5% / +1.6% / 356 | +0.3 |  |
| NBA altitude: visitor on a back-to-back at Denver/Utah, bet home ATS | 50.0% / -4.5% / 148 | 53.4% / +2.0% / 73 | +0.2 |  |
| Third straight road game: fade the road team ATS | 53.6% / +4.7% / 56 | 53.1% / +1.9% / 49 | +0.1 |  |
| Dome team outdoors at 40F or colder: bet home ATS | 63.5% / +22.7% / 104 | 51.9% / +0.7% / 129 | +0.1 |  |
| Referee home-cover rate 45% or less: bet away ATS | 50.7% / -1.6% / 538 | 51.6% / -0.1% / 677 | -0.0 |  |
| Referee home-cover rate 55%+: bet home ATS | 47.4% / -8.8% / 384 | 51.3% / -0.5% / 318 | -0.1 |  |
| Coach covers 58%+ as a 3+ point dog (past games): back him | 50.5% / -2.4% / 212 | 50.0% / -3.7% / 300 | -0.7 |  |
| NHL 4th+ straight road game: bet home ML | 55.8% / -2.1% / 971 | 54.9% / -2.6% / 898 | -0.9 |  |
| Revenge: lost the first meeting by 14+, back it ATS | 51.5% / -0.6% / 233 | 48.6% / -5.9% / 212 | -0.9 |  |
| NHL both teams on a back-to-back: bet the under | 52.4% / +2.5% / 290 | 49.7% / -4.1% / 626 | -1.0 |  |
| NBA both teams on a back-to-back: bet the under | 49.5% / -5.5% / 507 | 48.0% / -8.4% / 223 | -1.3 |  |
| Altitude: Denver at home, bet the over | 56.2% / +8.3% / 112 | 45.8% / -11.7% / 118 | -1.3 |  |
| Referee over-rate 55%+ (past games): bet over | 51.7% / +0.1% / 482 | 47.6% / -7.5% / 349 | -1.4 |  |
| NBA visitor on 3 games in 4 nights vs rested home: bet home ATS | 49.3% / -5.9% / 1377 | 49.2% / -6.1% / 903 | -1.9 |  |
| Travel 2,000+ miles: bet home ATS | 52.7% / +1.9% / 355 | 45.4% / -11.9% / 368 | -2.4 |  |
| NBA 4th+ straight road game: bet home ATS | 47.9% / -8.6% / 821 | 46.6% / -11.0% / 708 | -3.1 |  |

23 rules scored, so about one would show test z 2+ by luck alone.
