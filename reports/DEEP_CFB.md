# Deep model: CFB

16,264 games, seasons 2004-2022, 26 point-in-time features. Every prediction comes from a model trained only on earlier seasons. Thresholds chosen on 2012-2016; results below are on 2017-2022, which the choice never saw. Bets are at -110 (52.4% to break even).

Feature settings were tuned on the selection seasons only: Elo K 50, slow decay 0.08 (9 combinations tried).

## Spread (target: result minus closing line)

Market-only error on unseen seasons: 15.759 points.

| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 15.888 | no | 1.5 pts | 1813 | 0.4992 | 0.4799 | -0.047 |
| ridge | 15.764 | no | 3.0 pts | 130 | 0.5385 | 0.4665 | 0.028 |

Promoted: none (the closing line stays the champion)

## Total (target: result minus closing line)

Market-only error on unseen seasons: 16.316 points.

| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 16.393 | no | 3.0 pts | 446 | 0.4978 | 0.4589 | -0.0497 |
| ridge | 16.336 | no | 3.0 pts | 25 | 0.64 | 0.4757 | 0.2218 |

Promoted: none (the closing line stays the champion)

## Moneyline (target: win minus de-vigged closing probability; bets at the real closing price)

10,063 games with usable closing odds. Market-only Brier score on unseen seasons: 0.16593.

| Model | Brier | Beats market? | Min edge | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 0.16732 | no | 0% | 2710 | 0.4863 | 0.4706 | 0.1221 |
| ridge | 0.16622 | no | 0% | 1974 | 0.4716 | 0.4532 | 0.2048 |

Promoted: none (the closing line stays the champion)

Two models x 3 markets were tried, so one can look good by luck; a promoted model is trusted only after it keeps winning on new games logged by the app. Spread and total bets assume -110; moneyline bets use the actual closing price.