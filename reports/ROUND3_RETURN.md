# Strategy search, round 3: return next to win rate

Every rule is scored on seasons it never saw. Settings and thresholds were chosen on the earlier
(discovery) seasons only; the test seasons were looked at once. Return is profit per $1 staked at the
price actually listed (the opening moneyline, or the listed spread/total odds, else -110).
Recommend-only research: nothing here bets.

Data hygiene: about 40% of MLB archive rows pair two prices with no bookmaker margin (mismatched
sides or books) and 260 NFL rows carry the total in the closing-spread field. Both inflated returns
badly on a first pass (a fake 75% NFL spread system), so those rows are dropped before scoring.

## NHL moneyline: Elo vs the line (test seasons 2017 on)

Elo tuned on discovery seasons: K 8, home edge 35, carry-over 0.5, margin on (log loss 0.6756).

| Bet the model side when it beats the market by | Line | Discovery win / return / bets | Test win / return / bets |
|---|---|---|---|
| 3% | open | 46.0% / -6.3% / 2064 | 42.0% / -5.3% / 3241 |
| 3% | close | 44.3% / -6.8% / 2837 | 41.0% / -5.6% / 3635 |
| 5% | open | 45.8% / -2.6% / 729 | 40.1% / -4.7% / 1873 |
| 5% | close | 43.5% / -5.0% / 1404 | 38.9% / -7.2% / 2346 |
| 8% | open | 44.8% / -0.7% / 105 | 38.5% / -0.2% / 860 |
| 8% | close | 41.0% / -6.6% / 344 | 37.6% / -4.4% / 1083 |
| 10% | open | 46.3% / +3.0% / 41 | 37.5% / +3.6% / 530 |
| 10% | close | 45.5% / +6.5% / 132 | 35.8% / -4.9% / 631 |

## MLB moneyline: Elo vs the line (test seasons 2017 on)

Elo tuned on discovery seasons: K 4, home edge 20, carry-over 0.5, margin off (log loss 0.6977).

| Bet the model side when it beats the market by | Line | Discovery win / return / bets | Test win / return / bets |
|---|---|---|---|
| 3% | open | 46.2% / +1.5% / 2559 | 43.8% / -2.3% / 1775 |
| 3% | close | 47.0% / +3.5% / 2330 | 44.8% / +1.4% / 1639 |
| 5% | open | 45.8% / +2.9% / 2083 | 43.4% / -1.2% / 1441 |
| 5% | close | 46.5% / +4.9% / 1867 | 43.3% / +0.6% / 1366 |
| 8% | open | 44.4% / +3.9% / 1336 | 41.7% / -1.3% / 984 |
| 8% | close | 44.8% / +4.9% / 1243 | 41.1% / -0.7% / 975 |
| 10% | open | 44.1% / +6.0% / 943 | 40.4% / -0.8% / 678 |
| 10% | close | 42.9% / +3.7% / 846 | 40.2% / +0.6% / 721 |

## NBA moneyline: Elo vs the line (test seasons 2017 on)

Elo tuned on discovery seasons: K 8, home edge 65, carry-over 0.5, margin on (log loss 0.6021).

| Bet the model side when it beats the market by | Line | Discovery win / return / bets | Test win / return / bets |
|---|---|---|---|
| 3% | close | 36.2% / -4.2% / 4695 | 38.9% / -1.2% / 4741 |
| 5% | close | 34.6% / -4.9% / 3544 | 38.4% / +1.3% / 3808 |
| 8% | close | 33.8% / +0.5% / 2189 | 36.3% / -0.5% / 2593 |
| 10% | close | 33.2% / +1.7% / 1544 | 35.4% / -0.3% / 1974 |

## NFL moneyline: Elo vs the line (test seasons 2017 on)

Elo tuned on discovery seasons: K 20, home edge 65, carry-over 0.5, margin on (log loss 0.6204).

| Bet the model side when it beats the market by | Line | Discovery win / return / bets | Test win / return / bets |
|---|---|---|---|
| 3% | close | 45.3% / -1.1% / 946 | 38.8% / -7.5% / 1005 |
| 5% | close | 45.6% / +3.1% / 723 | 37.9% / -7.8% / 781 |
| 8% | close | 45.7% / +9.8% / 435 | 37.1% / -2.8% / 528 |
| 10% | close | 45.5% / +13.6% / 308 | 37.3% / -0.3% / 389 |

## NFL spread: Elo margin vs the line (test seasons 2017 on)

| Bet when model and line differ by | Line | Discovery win / return / bets | Test win / return / bets |
|---|---|---|---|
| 2 pts | open | 53.7% / +2.6% / 551 | 52.5% / +0.2% / 623 |
| 2 pts | close | 53.4% / +2.0% / 526 | 51.2% / -2.2% / 607 |
| 3 pts | open | 53.3% / +1.7% / 291 | 55.9% / +6.7% / 390 |
| 3 pts | close | 51.9% / -1.0% / 322 | 53.2% / +1.5% / 393 |
| 4 pts | open | 52.2% / -0.4% / 161 | 57.6% / +10.0% / 243 |
| 4 pts | close | 51.4% / -1.8% / 175 | 53.9% / +3.0% / 254 |
| 5 pts | open | 54.3% / +3.7% / 81 | 54.3% / +3.7% / 151 |
| 5 pts | close | 52.7% / +0.7% / 91 | 56.1% / +7.1% / 148 |

## NFL situations (nflverse 1999-2025, test seasons 2013 on)

| Rule | Discovery win / return / bets | Test win / return / bets |
|---|---|---|
| West-coast road team in a 1 PM ET kickoff: bet home ATS | 56.5% / +10.2% / 237 | 47.1% / -8.9% / 238 |
| Thursday night: bet the under | 57.0% / +11.2% / 93 | 47.7% / -7.2% / 241 |
| Primetime (Sun/Mon night): bet the under | 51.4% / +0.6% / 321 | 53.2% / +3.3% / 491 |
| Freezing (32F or colder, outdoors): bet the under | 44.9% / -13.5% / 205 | 49.4% / -4.4% / 172 |
| Team off a bye vs team that played: bet rested team ATS | 52.8% / +2.0% / 375 | 48.9% / -5.0% / 333 |
| Divisional game, total 41 or less: bet the over | 49.8% / -4.2% / 715 | 49.4% / -4.4% / 253 |
| Playoffs: bet the home favourite ATS | 48.0% / -7.4% / 125 | 47.5% / -8.0% / 122 |

## Leads: positive return in discovery AND test, 100+ test bets

- **NFL spread, model vs closing line by 5 pts**: test 56.1% win, +7.1% return on 148 bets (discovery 52.7%, +0.7%)
- **NFL spread, model vs opening line by 3 pts**: test 55.9% win, +6.7% return on 390 bets (discovery 53.3%, +1.7%)
- **NFL spread, model vs opening line by 5 pts**: test 54.3% win, +3.7% return on 151 bets (discovery 54.3%, +3.7%)
- **NHL ML, model beats opening line by 10%**: test 37.5% win, +3.6% return on 530 bets (discovery 46.3%, +3.0%)
- **Primetime (Sun/Mon night): bet the under**: test 53.2% win, +3.3% return on 491 bets (discovery 51.4%, +0.6%)
- **MLB ML, model beats closing line by 3%**: test 44.8% win, +1.4% return on 1639 bets (discovery 47.0%, +3.5%)
- **MLB ML, model beats closing line by 10%**: test 40.2% win, +0.6% return on 721 bets (discovery 42.9%, +3.7%)
- **MLB ML, model beats closing line by 5%**: test 43.3% win, +0.6% return on 1366 bets (discovery 46.5%, +4.9%)
- **NFL spread, model vs opening line by 2 pts**: test 52.5% win, +0.2% return on 623 bets (discovery 53.7%, +2.6%)

39 rule/threshold combinations were scored, so a few positive test results are expected by luck alone.
Treat a lead as worth paper-testing, not as proven.
