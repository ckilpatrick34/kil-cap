# Crypto strategies on unseen years (fee 0.25% per side)

Selection years 2016-2020, test years 2021-latest. Win = test-year CAGR > 0, Sharpe above buy-and-hold AND smaller max drawdown.

| coin | rule | test CAGR | test Sharpe | test max DD | sel Sharpe | luck p | win |
|---|---|---|---|---|---|---|---|
| btc | buy_hold | +13% | 0.50 | 77% | 1.49 | - | - |
| btc | trend_200 | +14% | 0.53 | 65% | 1.61 | 0.0 | YES |
| btc | sma_cross | +17% | 0.58 | 43% | 1.55 | 0.03333333333333333 | YES |
| btc | donchian | +13% | 0.53 | 57% | 1.89 | 0.0 | YES |
| btc | tsmom | +18% | 0.73 | 40% | 1.93 | 0.0 | YES |
| btc | trend_ensemble | +13% | 0.63 | 36% | 2.19 | 0.0 | YES |
| btc | rsi2_pullback | +5% | 0.34 | 35% | 0.41 | 0.11666666666666667 | no |
| eth | buy_hold | +22% | 0.64 | 79% | 1.73 | - | - |
| eth | trend_200 | +43% | 0.90 | 59% | 1.53 | 0.03333333333333333 | YES |
| eth | sma_cross | +25% | 0.67 | 73% | 1.92 | 0.0 | YES |
| eth | donchian | +34% | 0.84 | 53% | 2.24 | 0.0 | YES |
| eth | tsmom | +22% | 0.79 | 37% | 2.04 | 0.0 | YES |
| eth | trend_ensemble | +20% | 0.85 | 30% | 2.21 | 0.0 | YES |
| eth | rsi2_pullback | +5% | 0.31 | 26% | 0.19 | 0.4666666666666667 | no |
| ltc | buy_hold | -15% | 0.23 | 89% | 1.16 | - | - |
| ltc | trend_200 | -15% | 0.05 | 86% | 1.08 | 0.016666666666666666 | no |
| ltc | sma_cross | -7% | 0.23 | 82% | 1.27 | 0.016666666666666666 | no |
| ltc | donchian | -32% | -0.51 | 93% | 1.09 | 0.23333333333333334 | no |
| ltc | tsmom | -15% | -0.35 | 72% | 0.99 | 0.13333333333333333 | no |
| ltc | trend_ensemble | -5% | -0.08 | 49% | 1.04 | 0.05 | no |
| ltc | rsi2_pullback | -1% | 0.13 | 66% | 0.62 | 0.03333333333333333 | no |
| xrp | buy_hold | +40% | 0.80 | 83% | 1.10 | - | - |
| xrp | trend_200 | -1% | 0.36 | 92% | 0.87 | 0.4666666666666667 | no |
| xrp | sma_cross | -3% | 0.30 | 91% | 0.86 | 0.48333333333333334 | no |
| xrp | donchian | +42% | 0.86 | 69% | 1.23 | 0.0 | YES |
| xrp | tsmom | +8% | 0.39 | 49% | 0.98 | 0.08333333333333333 | no |
| xrp | trend_ensemble | +13% | 0.59 | 36% | 1.04 | 0.13333333333333333 | no |
| xrp | rsi2_pullback | +9% | 0.42 | 29% | -0.56 | 0.85 | no |
| doge | buy_hold | +77% | 0.88 | 92% | 1.15 | - | - |
| doge | trend_200 | +82% | 0.84 | 90% | 0.86 | 0.06666666666666667 | no |
| doge | sma_cross | +69% | 0.79 | 94% | 1.05 | 0.03333333333333333 | no |
| doge | donchian | +94% | 1.06 | 68% | 1.41 | 0.0 | YES |
| doge | tsmom | +46% | 1.04 | 33% | 1.03 | 0.0 | YES |
| doge | trend_ensemble | +34% | 1.04 | 30% | 1.28 | 0.0 | YES |
| doge | rsi2_pullback | +20% | 0.42 | 66% | -0.12 | 0.3333333333333333 | no |

| portfolio | test CAGR | test Sharpe | test max DD | sel CAGR | sel Sharpe |
|---|---|---|---|---|---|
| rotation | +18% | 0.67 | 41% | +55% | 1.48 |
| equal_weight_hold | +39% | 0.80 | 80% | +211% | 1.73 |
| btc_trend_mvrv | +14% | 0.52 | 65% | +113% | 1.55 |

Coins won per rule (of 5): donchian 4, trend_ensemble 3, tsmom 3, sma_cross 2, trend_200 2, rsi2_pullback 0
