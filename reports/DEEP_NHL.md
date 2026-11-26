# Deep model: NHL

13,581 games, seasons 2011-2021, 26 point-in-time features. Every prediction comes from a model trained only on earlier seasons. Thresholds chosen on 2014-2017; results below are on 2018-2021, which the choice never saw. Bets are at -110 (52.4% to break even).

Feature settings were tuned on the selection seasons only: Elo K 3, slow decay 0.06 (9 combinations tried).

## Spread (target: result minus closing line)

Market-only error on unseen seasons: nan points.

| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | nan | no | 0.0 pts | 0 | None | None | None |
| ridge | nan | no | 0.0 pts | 0 | None | None | None |

Promoted: none (the closing line stays the champion)

## Total (target: result minus closing line)

Market-only error on unseen seasons: 2.306 points.

| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 2.309 | no | 0.5 pts | 194 | 0.4948 | 0.4363 | -0.0553 |
| ridge | 2.301 | no | 0.0 pts | 4600 | 0.4983 | 0.4861 | -0.0488 |

Promoted: none (the closing line stays the champion)

## Moneyline (target: win minus de-vigged closing probability; bets at the real closing price)

13,580 games with usable closing odds. Market-only Brier score on unseen seasons: 0.23584.

| Model | Brier | Beats market? | Min edge | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 0.23787 | no | 10% | 484 | 0.4504 | 0.4136 | -0.067 |
| ridge | 0.23787 | no | 0% | 3309 | 0.4902 | 0.4759 | -0.0336 |

Promoted: none (the closing line stays the champion)

Two models x 3 markets were tried, so one can look good by luck; a promoted model is trusted only after it keeps winning on new games logged by the app. Spread and total bets assume -110; moneyline bets use the actual closing price.