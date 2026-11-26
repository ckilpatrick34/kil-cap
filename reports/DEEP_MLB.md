# Deep model: MLB

25,524 games, seasons 2011-2021, 26 point-in-time features. Every prediction comes from a model trained only on earlier seasons. Thresholds chosen on 2014-2017; results below are on 2018-2021, which the choice never saw. Bets are at -110 (52.4% to break even).

**DATA FAILED SANITY CHECKS - results below are NOT evidence of an edge. In this SBR archive home teams win only 43% of games, 64% of moneyline pairs are impossible (e.g. both sides favoured), and the closing total correlates only 0.10 with runs (0.02 in 2018). Rows are misaligned between games, so any 'edge' is an artifact.**

Feature settings were tuned on the selection seasons only: Elo K 2, slow decay 0.01 (9 combinations tried).

## Spread (target: result minus closing line)

Market-only error on unseen seasons: nan points.

| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | nan | no | 0.0 pts | 0 | None | None | None |
| ridge | nan | no | 0.0 pts | 0 | None | None | None |

Promoted: none (the closing line stays the champion)

## Total (target: result minus closing line)

Market-only error on unseen seasons: 5.051 points.

| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 5.013 | yes | 2.0 pts | 100 | 0.66 | 0.5788 | 0.26 |
| ridge | 4.679 | yes | 1.5 pts | 1225 | 0.6024 | 0.5792 | 0.1501 |

Promoted: gbm, ridge

## Moneyline (target: win minus de-vigged closing probability; bets at the real closing price)

9,124 games with usable closing odds. Market-only Brier score on unseen seasons: 0.22144.

| Model | Brier | Beats market? | Min edge | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 0.22764 | no | 6% | 1004 | 0.4671 | 0.4414 | -0.0306 |
| ridge | 0.22172 | no | 4% | 680 | 0.4721 | 0.4407 | 0.047 |

Promoted: none (the closing line stays the champion)

Two models x 3 markets were tried, so one can look good by luck; a promoted model is trusted only after it keeps winning on new games logged by the app. Spread and total bets assume -110; moneyline bets use the actual closing price.