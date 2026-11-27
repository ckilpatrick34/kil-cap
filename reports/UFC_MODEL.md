# UFC fight model: tested on fights it never saw

Built 2026-11-27 by `kil_capital/research/ufc_model.py`. Data: ufcstats.com via github.com/Greco1899/scrape_ufc_stats (every UFC fight since 1994, round-by-round stats) and closing-ish moneylines from github.com/shortlikeafox/ultimate_ufc_dataset (2010 to March 2026).

Each year is predicted by a model fit only on earlier fights. Settings were picked on 2016-2020 (discovery) and scored once on 2021-2026 (test).

## How often it picks the winner

| Years | Fights | Kil Cap model right | Vegas favourite right | Kil Cap log loss | Vegas log loss |
|---|---|---|---|---|---|
| 2016-2020 | 2157 | 60.9% | 64.6% | 0.6611 | 0.6177 |
| 2021-2026 | 2351 | 63.2% | 67.9% | 0.6400 | 0.5968 |

All fights 2016-2026 including those with no line: 5394 fights, model right 61.9%. Lower log loss is better; a coin flip scores 0.693.

## Does the model add anything to the Vegas line?

Blend = mix of our model and the de-vigged Vegas line (weight on our model). Picked on discovery years.

| Weight on Kil Cap | Discovery log loss | Test log loss |
|---|---|---|
| 0% | 0.6177 | 0.5968 |
| 5% | 0.6177 | 0.5970 |
| 10% | 0.6179 | 0.5973 |
| 15% | 0.6183 | 0.5978 |
| 20% | 0.6190 | 0.5985 |
| 30% | 0.6210 | 0.6006 |
| 50% | 0.6277 | 0.6073 |

Chosen weight: **0%**.

## Betting it: flat $10 at the listed moneyline

| Rule | Discovery bets | Discovery win % | Discovery return | Test bets | Test win % | Test return | Test $ P/L |
|---|---|---|---|---|---|---|---|
| Model beats price by 0% | 1915 | 39.9% | -7.3% | 2046 | 37.3% | -9.9% | -2035 |
| Model beats price by 3% | 1581 | 38.6% | -7.3% | 1690 | 36.1% | -9.8% | -1660 |
| Model beats price by 5% | 1357 | 37.6% | -6.9% | 1428 | 35.2% | -8.7% | -1240 |
| Model beats price by 8% | 1053 | 36.5% | -5.6% | 1110 | 34.5% | -6.8% | -754 |
| Model beats price by 12% | 702 | 36.3% | -3.5% | 760 | 33.2% | -5.4% | -411 |
| Blend (0%) beats price by 0% | 0 | 0.0% | +0.0% | 13 | 61.5% | +4.1% | +5 |
| Blend (0%) beats price by 1% | 0 | 0.0% | +0.0% | 12 | 58.3% | -1.2% | -1 |
| Blend (0%) beats price by 2% | 0 | 0.0% | +0.0% | 11 | 63.6% | +7.8% | +9 |
| Blend (0%) beats price by 4% | 0 | 0.0% | +0.0% | 10 | 60.0% | +2.3% | +2 |
| Back every fighter priced -10000 to -400 | 232 | 87.1% | +2.7% | 363 | 88.2% | +3.2% | +116 |
| Back every fighter priced -400 to -250 | 445 | 75.5% | -0.4% | 476 | 75.6% | +0.0% | +0 |
| Back every fighter priced -250 to -150 | 794 | 61.7% | -6.2% | 957 | 64.3% | -2.6% | -250 |
| Back every fighter priced -150 to +100 | 686 | 53.8% | -4.5% | 560 | 54.8% | -2.7% | -151 |
| Back every fighter priced +100 to +150 | 758 | 45.6% | +1.2% | 733 | 43.5% | -3.6% | -267 |
| Back every fighter priced +150 to +250 | 752 | 33.6% | -5.2% | 899 | 31.5% | -9.2% | -827 |
| Back every fighter priced +250 to +400 | 350 | 20.6% | -18.9% | 401 | 19.7% | -21.5% | -862 |
| Back every fighter priced +400 to +10000 | 141 | 10.6% | -34.2% | 205 | 8.8% | -46.3% | -950 |

## Verdict

- **Model beats price by**: best on discovery was `Model beats price by 12%` (-3.5%); on the test years it returned **-5.4%** over 760 bets.
- **Back every fighter priced**: best on discovery was `Back every fighter priced -10000 to -400` (+2.7%); on the test years it returned **+3.2%** over 363 bets.

The public fight stats are already in the Vegas price. The model alone loses money against the closing line at every threshold. The one rule that held on both periods is backing heavy favourites (-400 or shorter), worth about +3% on a few hundred bets: small, inside the noise, and it risks $10 to win about $2, so it is a lead to paper-track, not a bet. So the UFC tab treats Vegas as the anchor: the Kil Cap line is shown for comparison, and a BET only appears when Kalshi sells a fighter at least 3 cents under the fair price (blend of Vegas and Kil Cap, after Kalshi's fee), the same price-gap rule as the Book's `gap` sleeve. Judge it on graded bets and closing-line value, not on this backtest.
