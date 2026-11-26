# MLB moneyball model, first pass (2026-11-26)

Research on paper, not betting advice.

**Data.** Retrosheet play-by-play for 2012-2025, with scores from the Retrosheet game logs. Statcast data (xBA, xwOBA) is not included yet, because it can only be pulled from Carson's PC.

**Features.** All features are season-to-date as of before each game and pulled toward the league average. Each one is home minus visitor.
- Starting pitcher: xFIP per plate appearance, K-BB%, and wOBA allowed
- Bullpen: xFIP per plate appearance
- Team batting: wOBA
- Team run differential per game

**Model.** A logistic regression for whether the home team wins. It is trained on 2012-2019 and was never fit to 2021-2025. 2020 is skipped.

| Seasons | Games | Log loss | Home-team-only baseline | Accuracy |
| --- | --- | --- | --- | --- |
| 2021-22 (validation) | 4,725 | 0.6740 | 0.6904 | 57.7% |
| 2023-25 (test) | 4,727 | 0.6800 | 0.6912 | 55.7% |

Lower log loss is better. The model clearly beats the home-team baseline on seasons it never saw. Two features matter most: run differential and pitcher K-BB%. xFIP adds signal beyond wOBA allowed, which is the moneyball idea that skill stats beat results.

**Open question: does it beat the market?** That needs clean MLB moneylines. The SBR MLB archive we have is corrupt and must not be used. For reference only (unverified, from general knowledge), MLB closing lines usually score about 0.675-0.68 log loss, so this model is probably near the market, not above it. The real test is the ERA-versus-xFIP hypothesis: a pitcher whose results are lucky (low runs allowed, poor skill stats) may be overpriced. That test needs odds.

**Next steps**
1. Get clean odds, either from an odds API key or by downloading on the PC.
2. Add Statcast xwOBA and barrel rate, pulled on the PC with pybaseball.
3. Use prior-season stats as the starting point early in the season.
4. Build a totals model using the temperature and wind data already in the event files.

Code: `python -m kil_capital.research.mlb <retrosheet seasons dir>` (kil_capital/research/mlb.py).
