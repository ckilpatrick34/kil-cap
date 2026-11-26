# Deep model: NFL

7,440 games, seasons 1999-2026, 26 point-in-time features. Every prediction comes from a model trained only on earlier seasons. Thresholds chosen on 2006-2015; results below are on 2016-2026, which the choice never saw. Bets are at -110 (52.4% to break even).

Feature settings were tuned on the selection seasons only: Elo K 40, slow decay 0.16 (9 combinations tried).

## Spread (target: result minus closing line)

Market-only error on unseen seasons: 12.654 points.

| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 12.794 | no | 1.5 pts | 1202 | 0.4842 | 0.4605 | -0.0756 |
| ridge | 12.67 | no | 0.0 pts | 2854 | 0.5004 | 0.485 | -0.0448 |

Promoted: none (the closing line stays the champion)

## Total (target: result minus closing line)

Market-only error on unseen seasons: 13.216 points.

| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 13.357 | no | 1.0 pts | 1860 | 0.4957 | 0.4766 | -0.0537 |
| ridge | 13.196 | yes | 3.0 pts | 93 | 0.5269 | 0.4422 | 0.0059 |

Promoted: ridge

## Moneyline (target: win minus de-vigged closing probability; bets at the real closing price)

5,459 games with usable closing odds. Market-only Brier score on unseen seasons: 0.20987.

| Model | Brier | Beats market? | Min edge | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 0.21746 | no | 0% | 2471 | 0.5075 | 0.4909 | -0.024 |
| ridge | 0.21074 | no | 0% | 1912 | 0.4922 | 0.4734 | -0.0185 |

Promoted: none (the closing line stays the champion)

Two models x 3 markets were tried, so one can look good by luck; a promoted model is trusted only after it keeps winning on new games logged by the app. Spread and total bets assume -110; moneyline bets use the actual closing price.