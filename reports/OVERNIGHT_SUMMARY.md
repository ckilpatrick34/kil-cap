# Overnight: can a model beat Vegas? (2026-11-26)

Rule used for every league: features use only games played before each game, every model is trained
only on earlier seasons, settings and bet thresholds are picked on the first half of the test seasons,
and the numbers below come only from the second half, which no choice ever saw. "Beats Vegas" means
its error beats the closing line *and* it makes money on those unseen seasons.

| League | Data (seasons, games) | Spread | Total | Moneyline | Verdict |
|---|---|---|---|---|---|
| NFL | nflverse 1999-2026, 7,440 | no edge (50.0%, -4.5%) | ridge passes the error test but 52.7% on 93 bets, +0.6% ROI | no edge (-1.9%) | Does not beat Vegas. The earlier 63% totals result did not survive tuning. |
| College football | cfbfastR 2006-2022, 16,264 | no edge | no edge | ROI +20% but from 4 wins at +1000 or longer; error worse than market | Does not beat Vegas. |
| NBA | SBR 2011-2021, 13,893 | no edge (-4.4%) | no edge (-2.5%) | +1-2% ROI on long shots, error worse than market | Does not beat Vegas. |
| NHL | SBR 2011-2021, 13,581 | (puck line not in data) | no edge (-4.9%) | no edge (-3.4%) | Does not beat Vegas. |
| MLB | SBR 2011-2021, 25,524 | (run line not in data) | "60% / +15%" | no edge | **Data is broken** (home teams win 43%, 64% of moneylines impossible). The win is an artifact. |
| College basketball | none reachable | | | | Not done: no public closing-line history found. |
| College baseball, college hockey | none reachable | | | | Not done: no public line data exists that I could find. |

Bottom line: no league has a model that beats the closing line on unseen seasons. That matches what
the research literature finds for closing lines in major markets. The closing line stays the champion
in the app, and nothing new was promoted into live prices.

Where real edges are more likely (next steps that need data from the Mac or a paid feed):
1. Bet earlier than the close: test opening line vs closing line moves (the data has opening lines).
2. Smaller markets: college basketball totals (Big Vin's data showed CBB totals profitable), props.
3. Information the line is slow on: injuries/lineups, weather updates, starting goalies and pitchers.
4. Kalshi's own prices vs the sportsbook close: an edge may exist on Kalshi even where none exists vs Vegas.

Full per-league tables: DEEP_NFL.md, DEEP_CFB.md, DEEP_NBA.md, DEEP_NHL.md, DEEP_MLB.md.
