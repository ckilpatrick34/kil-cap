# Strategy search, 26 Nov 2026: closing-line systems and crypto

Every strategy here is judged only on seasons or years it never saw. "Win" in sports = beat 52.4%, which is break-even at -110.
Recommend-only research: nothing places bets or trades.

## Sports: three leads worth paper-testing

| Lead | Earlier seasons | Later (test) seasons | Strength |
|---|---|---|---|
| NBA: bet the OPENING total when a simple scoring model disagrees by 8.5+ pts | 56.1% on 446, +7.0% | 55.4% on 489, +5.8% | Best lead. Positive in most seasons, holds when settings change, and the line moved our way 60% of the time. |
| NFL: wind 15+ mph outdoors, bet the under | 58.0% on 407, +10.7% | 55.4% on 267, +5.8% | Real but weak (test z 1.0). Has a physical reason, but books price it more now. |
| NHL: low totals (bottom 10%), bet the over | 52.5% on 2,119 | 55.9% on 594, +6.7% | Weak. NHL totals carry extra juice, so -110 grading flatters it. |

What did not work (all at or below break-even on the later seasons): following or fading line moves at the close; key numbers (+3, +7, -2.5, +3.5); home dogs; big dogs; divisional dogs; playoff unders; high-total unders; and simple rating models against opening spreads in NBA and CFB.

**Biggest finding: betting the open is where the money is.** If you could bet the opening line in the direction it later moves, you'd hit 57-61% in every sport (NBA, CFB, NHL), over thousands of games. Sharp bettors make money by predicting line moves. A model that gets moves right 60% of the time is worth more than any closing-line system. The NBA totals lead above is a first version of that.

Caveats: the opening lines come from the SBR archive. Real openers carry low betting limits and sometimes worse than -110. NBA data ends in 2021. NHL "line moved our way" reads 100%, which points to a quirk in that league's opening-line data, so don't trust the NHL opener result.

40 systems were tested. About 2 would pass by luck alone, so only the NBA opener lead has strong evidence.

## Crypto: two strategies that won on unseen years (2021 to May 2026)

Data: BTC Bitstamp daily 2014-Nov 2026; ETH, LTC, XRP, DOGE from Coin Metrics to May 2026. Fee 0.25% per side. Rules are standard published ones, not tuned.

| BTC + ETH 50/50, test years 2021-May 2026 | CAGR | Sharpe | Max drawdown | 2022 (crash year) |
|---|---|---|---|---|
| Buy and hold | +24% | 0.65 | 76% | -65% |
| Donchian breakout (buy 20-day high, sell 10-day low) | +27% | 0.82 | 41% | -32% |
| Trend ensemble, sized to 40% annual volatility | +18% | 0.84 | 29% | -18% |
| Time-series momentum, vol-sized | +21% | 0.84 | 34% | -21% |

- Donchian beat buy-and-hold on 4 of 5 coins. Trend ensemble and momentum beat it on 3 of 5 (BTC, ETH, DOGE).
- They fail on coins in long declines: LTC in all cases, and XRP for most rules.
- These are not high-win-rate strategies. Only 18-48% of trades win. They make money by catching big trends and getting out before crashes, cutting the worst drawdown roughly in half.
- Mean reversion (RSI dip-buying, Bollinger bands) failed everywhere.

Reproduce: `python -m kil_capital.research.lines` (reports/LINE_SYSTEMS.md) and `python -m kil_capital.research.crypto_deep` (reports/CRYPTO_UNSEEN.md).
