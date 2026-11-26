# Deep model: NBA

13,893 games, seasons 2011-2021, 26 point-in-time features. Every prediction comes from a model trained only on earlier seasons. Thresholds chosen on 2014-2017; results below are on 2018-2021, which the choice never saw. Bets are at -110 (52.4% to break even).

Feature settings were tuned on the selection seasons only: Elo K 40, slow decay 0.02 (9 combinations tried).

## Spread (target: result minus closing line)

Market-only error on unseen seasons: 13.154 points.

| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 13.21 | no | 2.0 pts | 717 | 0.5007 | 0.47 | -0.0441 |
| ridge | 13.188 | no | 0.5 pts | 2286 | 0.4847 | 0.4675 | -0.0747 |

Promoted: none (the closing line stays the champion)

## Total (target: result minus closing line)

Market-only error on unseen seasons: 18.41 points.

| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 18.581 | no | 1.0 pts | 2061 | 0.5109 | 0.4928 | -0.0246 |
| ridge | 18.558 | no | 3.0 pts | 495 | 0.4869 | 0.4501 | -0.0705 |

Promoted: none (the closing line stays the champion)

## Moneyline (target: win minus de-vigged closing probability; bets at the real closing price)

13,885 games with usable closing odds. Market-only Brier score on unseen seasons: 0.2102.

| Model | Brier | Beats market? | Min edge | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 0.21149 | no | 10% | 531 | 0.3126 | 0.2805 | 0.0119 |
| ridge | 0.21186 | no | 10% | 649 | 0.2219 | 0.1962 | 0.0221 |

Promoted: none (the closing line stays the champion)

Two models x 3 markets were tried, so one can look good by luck; a promoted model is trusted only after it keeps winning on new games logged by the app. Spread and total bets assume -110; moneyline bets use the actual closing price.