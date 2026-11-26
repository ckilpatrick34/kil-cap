# Deep model: NFL

7,440 games, seasons 1999-2026, 25 point-in-time features. Every prediction comes from a model trained only on earlier seasons. Thresholds chosen on 2006-2015; results below are on 2016-2026, which the choice never saw. Bets are at -110 (52.4% to break even).

## Spread (target: result minus closing line)

Market-only error on unseen seasons: 12.654 points.

| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 12.777 | no | 2.0 pts | 934 | 0.5054 | 0.4785 | -0.0352 |
| ridge | 12.679 | no | 0.5 pts | 1881 | 0.4987 | 0.4797 | -0.048 |

Promoted: none (the closing line stays the champion)

## Total (target: result minus closing line)

Market-only error on unseen seasons: 13.216 points.

| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |
|---|---|---|---|---|---|---|---|
| gbm | 13.387 | no | 3.0 pts | 520 | 0.4712 | 0.4354 | -0.1005 |
| ridge | 13.198 | yes | 3.0 pts | 114 | 0.6316 | 0.555 | 0.2057 |

Promoted: ridge

Two models x two markets were tried, so one of four can look good by luck; a promoted model is trusted only after it keeps winning on new games logged by the app.