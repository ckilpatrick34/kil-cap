# Brute-force edge search (2026-11-26)

## Bottom line

No rule-based edge holds up on the newest seasons. Roughly 30,000 to 60,000 rules per market were tried across NFL, college football, NBA and NHL, at the closing line and (where the data has it) the opening line.

* **NHL opening line and CFB opening line** found far more rules than luck does (60 vs about 5, and 76 vs about 27), so there were real patterns in the older seasons. But on the newest seasons those same rules won only 50.6% and 50.5%, below the 52.4% needed to profit at -110. The patterns faded, most likely because the markets got sharper.
* **NFL closing line** won 54.6% on the newest seasons (231/423), but the search found fewer rules than shuffled data does, so this is within what luck produces (about 1 standard deviation above break-even). Worth paper-tracking, not trusting.
* **Everything else** is at or below break-even on the newest seasons.
* **A bug was caught and fixed before this report.** The first run showed NBA opening-line rules winning 54% on unseen seasons. Those rules were reading the *closing* spread and total while betting the *opening* line, which is looking into the future. With opening-line features only, NBA opening falls to 51.1% and to fewer survivors than luck. The 54% was not real.

The individual rules listed under each market and at the end ("won 55%+ on the holdout") are hand-picked winners from many tries, so they will look better than they are. Only the "each game once" holdout line and the luck comparison are fair tests.

Every 1-, 2- and 3-condition rule over the pre-game features below, for home/away against the spread and over/under. Seasons are cut in three: **discovery** (oldest half) picks rules that won 56%+ with z 3+ on 100+ bets; **validation** (next quarter) keeps those still above 52.4%; **holdout** (newest quarter) is looked at once, at the end. At the opening line, every line-based feature uses the opening number. The **shuffle test** runs the identical search on outcomes randomly reassigned within each season: it is how many rules luck alone sends through. A real edge shows up as more survivors than the shuffle AND a holdout win rate above 52.4%.

## NFL closing line

7440 games, 168 conditions. Discovery 1999-2012, validation 2013-2019, holdout 2020-2026.

* Real data: 78 rules pass discovery, 19 also pass validation (13 distinct ideas).
* Shuffled data (20 runs, discovery->validation): median 26, 90th percentile 80, max 177 survivors.
* Distinct surviving ideas on the holdout, pooled: 530/965 = 54.9%.
* Every surviving rule on the holdout, each game counted once: 231/423 = 54.6% (by season: 2020 49/79, 2021 48/74, 2022 32/61, 2023 28/61, 2024 34/58, 2025 26/64, 2026 14/26).

| Rule | Discovery | Validation | Holdout |
|---|---|---|---|
| neutral = 0 AND streak_h <= -1 AND wp_a <= 0.154 -> away ATS | 107/165 64.8% | 48/83 57.8% | 49/82 59.8% |
| streak_h <= -1 AND wp_a <= 0.154 -> away ATS | 107/165 64.8% | 48/84 57.1% | 49/82 59.8% |
| playoff = 0 AND streak_h <= -1 AND wp_a <= 0.154 -> away ATS | 107/165 64.8% | 48/84 57.1% | 49/82 59.8% |
| rest_diff >= -1 AND streak_h <= -1 AND wp_a <= 0.154 -> away ATS | 100/154 64.9% | 43/75 57.3% | 45/78 57.7% |
| pa_a >= 21.9 AND pa_h >= 22 AND temp <= 54 -> under | 115/178 64.6% | 86/160 53.8% | 94/155 60.6% |
| rest_h >= 6 AND streak_h <= -1 AND wp_a <= 0.154 -> away ATS | 106/160 66.2% | 44/78 56.4% | 45/78 57.7% |
| rest_h <= 7 AND streak_h <= -1 AND wind <= 2 -> home ATS | 79/119 66.4% | 31/50 62.0% | 18/36 50.0% |
| pa_a <= 19.7 AND pa_h >= 22 AND streak_a >= 3 -> over | 69/101 68.3% | 32/58 55.2% | 18/31 58.1% |
| rest_a >= 7 AND streak_h <= -1 AND wp_a <= 0.154 -> away ATS | 101/151 66.9% | 37/69 53.6% | 42/73 57.5% |
| atsp_a >= 0.667 AND rest_diff <= -1 AND rest_h <= 10 -> over | 84/127 66.1% | 45/85 52.9% | 37/76 48.7% |
| lastm_h <= -13 AND ovp_a <= 0.333 AND rest_a <= 7 -> away ATS | 94/144 65.3% | 37/67 55.2% | 29/63 46.0% |
| lastm_h <= -13 AND ovp_a <= 0.333 AND rest_h <= 7 -> away ATS | 97/147 66.0% | 34/64 53.1% | 28/64 43.8% |
| lastm_h <= -13 AND ovp_a <= 0.333 AND rest_diff <= 0 -> away ATS | 92/137 67.2% | 34/63 54.0% | 27/65 41.5% |

## CFB closing line

16264 games, 176 conditions. Discovery 2004-2012, validation 2013-2017, holdout 2018-2022.

* Real data: 54 rules pass discovery, 35 also pass validation (21 distinct ideas).
* Shuffled data (20 runs, discovery->validation): median 15, 90th percentile 66, max 111 survivors.
* Distinct surviving ideas on the holdout, pooled: 1981/4008 = 49.4%.
* Every surviving rule on the holdout, each game counted once: 817/1619 = 50.5% (by season: 2018 220/421, 2019 169/368, 2020 3/7, 2021 217/412, 2022 208/411).

| Rule | Discovery | Validation | Holdout |
|---|---|---|---|
| ovp_a <= 0.429 AND total_move <= 0 AND wp_diff <= -0.275 -> away ATS | 98/150 65.3% | 75/125 60.0% | 59/111 53.2% |
| ovp_a <= 0.429 AND rest_a >= 7 AND wp_diff <= -0.275 -> away ATS | 100/154 64.9% | 131/226 58.0% | 90/172 52.3% |
| ovp_a <= 0.429 AND rest_h <= 8 AND wp_diff <= -0.275 -> away ATS | 96/145 66.2% | 117/203 57.6% | 79/153 51.6% |
| abs_spread_move <= 0 AND pa_a >= 26.4 AND pf_a >= 29.4 -> home ATS | 118/186 63.4% | 37/65 56.9% | 41/77 53.2% |
| abs_spread <= 3.5 AND lastm_a >= 5 AND rest_diff <= 0 -> away ATS | 171/273 62.6% | 155/267 58.1% | 130/254 51.2% |
| abs_spread <= 7 AND lastm_a >= 31 AND total_move <= 0 -> under | 90/136 66.2% | 61/110 55.5% | 51/95 53.7% |
| ovp_a <= 0.429 AND rest_diff <= 2 AND wp_diff <= -0.275 -> away ATS | 100/152 65.8% | 124/220 56.4% | 87/167 52.1% |
| ovp_a <= 0.25 AND wp_diff >= 0.0833 AND wp_h >= 0.667 -> away ATS | 73/109 67.0% | 64/117 54.7% | 49/91 53.8% |
| abs_spread <= 3.5 AND rest_diff <= 0 AND wp_a >= 0.667 -> away ATS | 153/242 63.2% | 148/256 57.8% | 115/234 49.1% |
| atsp_h >= 0.571 AND rest_h <= 8 AND wp_a >= 1 -> away ATS | 82/124 66.1% | 97/170 57.1% | 72/146 49.3% |
| lastm_a >= 20 AND model_total_gap >= 0.595 AND ovp_a >= 0.5 -> under | 92/136 67.6% | 93/170 54.7% | 77/148 52.0% |
| atsp_h >= 0.571 AND rest_diff <= 0 AND wp_a >= 0.833 -> away ATS | 119/187 63.6% | 129/237 54.4% | 102/200 51.0% |
| abs_spread <= 3.5 AND lastm_a >= 5 AND rest_h <= 8 -> away ATS | 165/264 62.5% | 153/271 56.5% | 125/260 48.1% |
| abs_spread <= 3.5 AND rest_h <= 8 AND wp_a >= 0.667 -> away ATS | 145/229 63.3% | 145/257 56.4% | 111/232 47.8% |
| abs_spread <= 7 AND abs_spread_move >= 0.5 AND atsp_h <= 0.5 -> away ATS | 92/141 65.2% | 379/717 52.9% | 294/578 50.9% |

## CFB opening line

12050 games, 150 conditions. Discovery 2006-2013, validation 2014-2017, holdout 2018-2022.

* Real data: 226 rules pass discovery, 76 also pass validation (44 distinct ideas).
* Shuffled data (20 runs, discovery->validation): median 24, 90th percentile 53, max 68 survivors.
* Distinct surviving ideas on the holdout, pooled: 3006/5907 = 50.9%.
* Every surviving rule on the holdout, each game counted once: 840/1663 = 50.5% (by season: 2018 230/427, 2019 199/384, 2020 10/24, 2021 200/399, 2022 201/429).

| Rule | Discovery | Validation | Holdout |
|---|---|---|---|
| abs_spread <= 3.5 AND model_margin_gap <= -5.58 AND rest_diff <= 0 -> away ATS | 80/119 67.2% | 46/73 63.0% | 42/71 59.2% |
| model_margin_gap <= -5.58 AND rest_a <= 8 AND spread <= 3 -> away ATS | 84/125 67.2% | 45/71 63.4% | 47/85 55.3% |
| abs_spread <= 3.5 AND dome = 0 AND model_margin_gap <= -5.58 -> away ATS | 93/142 65.5% | 53/90 58.9% | 52/89 58.4% |
| abs_spread <= 3.5 AND model_margin_gap <= -5.58 AND neutral = 0 -> away ATS | 93/143 65.0% | 54/92 58.7% | 51/88 58.0% |
| abs_spread <= 3.5 AND model_margin_gap <= -5.58 AND rest_h <= 14 -> away ATS | 91/138 65.9% | 54/91 59.3% | 50/88 56.8% |
| model_margin_gap <= -5.58 AND rest_h <= 14 AND spread <= 3 -> away ATS | 98/151 64.9% | 55/90 61.1% | 54/98 55.1% |
| atsp_a <= 0.444 AND rest_diff <= 0 AND total <= 47 -> away ATS | 151/241 62.7% | 70/115 60.9% | 74/134 55.2% |
| abs_spread <= 3.5 AND model_margin_gap <= -5.58 AND rest_a <= 14 -> away ATS | 90/138 65.2% | 54/92 58.7% | 50/88 56.8% |
| abs_spread <= 3.5 AND model_margin_gap <= -5.58 AND wp_diff <= -0.0833 -> away ATS | 81/118 68.6% | 39/68 57.4% | 39/68 57.4% |
| atsp_a <= 0.444 AND rest_h <= 8 AND total <= 47 -> away ATS | 150/237 63.3% | 68/113 60.2% | 71/133 53.4% |
| model_margin_gap <= -5.58 AND spread <= 3 AND wp_diff <= -0.0833 -> away ATS | 95/143 66.4% | 42/71 59.2% | 45/83 54.2% |
| model_margin_gap <= -5.58 AND rest_diff >= 0 AND spread <= 3 -> away ATS | 89/135 65.9% | 45/77 58.4% | 46/85 54.1% |
| atsp_a <= 0.444 AND lastm_h <= -4 AND total <= 47 -> away ATS | 96/134 71.6% | 30/51 58.8% | 39/72 54.2% |
| abs_spread <= 7 AND model_margin_gap <= -5.58 AND spread <= 3 -> away ATS | 93/140 66.4% | 48/84 57.1% | 50/91 54.9% |
| ovp_a <= 0.429 AND rest_diff <= 0 AND wp_diff <= -0.273 -> away ATS | 117/181 64.6% | 99/175 56.6% | 85/156 54.5% |

## NBA closing line

13893 games, 178 conditions. Discovery 2011-2015, validation 2016-2018, holdout 2019-2021.

* Real data: 174 rules pass discovery, 34 also pass validation (30 distinct ideas).
* Shuffled data (20 runs, discovery->validation): median 22, 90th percentile 51, max 74 survivors.
* Distinct surviving ideas on the holdout, pooled: 1881/3854 = 48.8%.
* Every surviving rule on the holdout, each game counted once: 729/1473 = 49.5% (by season: 2019 251/484, 2020 219/445, 2021 259/544).

| Rule | Discovery | Validation | Holdout |
|---|---|---|---|
| abs_spread_move <= 0.5 AND atsp_a <= 0.429 AND ovp_h >= 0.56 -> away ATS | 93/143 65.0% | 52/91 57.1% | 40/65 61.5% |
| lastm_h >= 4 AND total_move <= -2 AND week_frac <= 16 -> under | 76/114 66.7% | 55/95 57.9% | 39/65 60.0% |
| pa_a <= 97.9 AND pf_h >= 103 AND total >= 202 -> under | 114/179 63.7% | 36/65 55.4% | 12/17 70.6% |
| streak_h >= 1 AND total_move <= -2 AND week_frac <= 16 -> under | 87/133 65.4% | 64/113 56.6% | 46/80 57.5% |
| abs_spread_move <= 0 AND model_total_gap >= 3.76 AND streak_a <= -1 -> away ATS | 72/107 67.3% | 25/43 58.1% | 28/50 56.0% |
| abs_total_move >= 3.5 AND atsp_a >= 0.574 AND total_move >= 0.5 -> over | 72/106 67.9% | 50/83 60.2% | 43/81 53.1% |
| abs_spread_move <= 0.5 AND lastm_a <= -17 AND ovp_a >= 0.513 -> away ATS | 80/120 66.7% | 43/82 52.4% | 42/69 60.9% |
| total_move <= -0.5 AND week_frac <= 16 AND wp_h >= 0.667 -> under | 98/150 65.3% | 45/80 56.2% | 46/89 51.7% |
| abs_spread_move <= 0.5 AND streak_a <= -1 AND total_move <= -2 -> away ATS | 181/296 61.1% | 91/162 56.2% | 82/160 51.2% |
| abs_total_move <= 0.5 AND ovp_a <= 0.48 AND ovp_h <= 0.423 -> over | 100/152 65.8% | 33/55 60.0% | 37/77 48.1% |
| abs_spread_move <= 0.5 AND streak_a <= -1 AND wp_h <= 0.348 -> away ATS | 185/299 61.9% | 90/158 57.0% | 58/123 47.2% |
| abs_total_move <= 0.5 AND ovp_h <= 0.423 AND wp_a >= 0.565 -> over | 88/125 70.4% | 34/61 55.7% | 28/57 49.1% |
| abs_total_move <= 1 AND streak_h <= -2 AND total >= 208 -> under | 77/114 67.5% | 143/265 54.0% | 126/249 50.6% |
| abs_spread_move <= 0.5 AND lastm_a <= -11 AND rest_h <= 2 -> away ATS | 284/478 59.4% | 148/278 53.2% | 122/243 50.2% |
| abs_spread_move <= 0.5 AND lastm_a <= -4 AND wp_h <= 0.471 -> away ATS | 291/491 59.3% | 151/262 57.6% | 101/225 44.9% |

## NBA opening line

12960 games, 148 conditions. Discovery 2011-2015, validation 2016-2018, holdout 2019-2021.

* Real data: 105 rules pass discovery, 10 also pass validation (10 distinct ideas).
* Shuffled data (20 runs, discovery->validation): median 13, 90th percentile 36, max 144 survivors.
* Distinct surviving ideas on the holdout, pooled: 1322/2567 = 51.5%.
* Every surviving rule on the holdout, each game counted once: 1149/2247 = 51.1% (by season: 2019 401/793, 2020 389/756, 2021 359/698).

| Rule | Discovery | Validation | Holdout |
|---|---|---|---|
| pa_a <= 97.9 AND pf_h >= 103 AND total >= 201 -> under | 119/186 64.0% | 43/68 63.2% | 12/17 70.6% |
| lastm_a >= 4 AND pa_a <= 97.9 AND pf_h >= 103 -> under | 119/183 65.0% | 34/61 55.7% | 10/12 83.3% |
| lastm_a <= -4 AND total >= 201 AND wp_diff <= -0.208 -> away ATS | 77/114 67.5% | 80/148 54.1% | 86/154 55.8% |
| ovp_a >= 0.513 AND rest_diff <= 0 AND spread >= 11 -> away ATS | 97/148 65.5% | 58/106 54.7% | 39/71 54.9% |
| abs_spread >= 11.5 AND lastm_h >= 4 AND streak_a <= -2 -> away ATS | 68/101 67.3% | 30/53 56.6% | 18/36 50.0% |
| pf_h >= 103 AND rest_diff >= 1 AND week_frac >= 50 -> under | 106/165 64.2% | 181/317 57.1% | 166/329 50.5% |
| model_margin_gap >= 0.332 AND ovp_a >= 0.513 AND ovp_h >= 0.513 -> away ATS | 129/205 62.9% | 100/187 53.5% | 87/162 53.7% |
| lastm_a <= -4 AND wp_a >= 0.56 AND wp_h <= 0.471 -> away ATS | 130/206 63.1% | 69/131 52.7% | 68/128 53.1% |
| lastm_a <= -4 AND week_frac <= 33 AND wp_h <= 0.348 -> away ATS | 136/217 62.7% | 74/137 54.0% | 58/117 49.6% |
| model_margin_gap >= -2.71 AND pa_a >= 104 AND pf_a >= 101 -> under | 76/110 69.1% | 557/1063 52.4% | 778/1541 50.5% |

## NHL closing line

13581 games, 110 conditions. Discovery 2011-2015, validation 2016-2018, holdout 2019-2021.

* Real data: 52 rules pass discovery, 15 also pass validation (15 distinct ideas).
* Shuffled data (20 runs, discovery->validation): median 3, 90th percentile 8, max 71 survivors.
* Distinct surviving ideas on the holdout, pooled: 1620/3208 = 50.5%.
* Every surviving rule on the holdout, each game counted once: 699/1380 = 50.7% (by season: 2019 259/501, 2020 204/377, 2021 236/502).

| Rule | Discovery | Validation | Holdout |
|---|---|---|---|
| lastm_a >= 2 AND pf_a <= 2.65 AND total >= 5.5 -> under | 117/183 63.9% | 59/105 56.2% | 70/120 58.3% |
| pa_h >= 3.04 AND pf_a <= 2.27 AND total_move <= 0 -> under | 84/128 65.6% | 30/55 54.5% | 44/77 57.1% |
| lastm_h >= 1 AND ovp_h >= 0.5 AND week_frac <= 16 -> under | 171/275 62.2% | 116/211 55.0% | 105/192 54.7% |
| model_total_gap <= -0.0225 AND ovp_h <= 0.4 AND total >= 5.5 -> under | 134/213 62.9% | 77/128 60.2% | 108/216 50.0% |
| pa_h >= 3.04 AND pf_a <= 2.27 AND rest_a >= 2 -> under | 70/102 68.6% | 25/47 53.2% | 34/63 54.0% |
| pf_a <= 2.65 AND rest_diff <= 1 AND total >= 5.5 -> under | 529/916 57.8% | 269/490 54.9% | 308/600 51.3% |
| ovp_a <= 0.46 AND pa_h >= 3.04 AND pf_a <= 2.27 -> under | 70/101 69.3% | 21/40 52.5% | 31/59 52.5% |
| lastm_h >= 1 AND pf_a <= 2.65 AND total >= 5.5 -> under | 311/525 59.2% | 169/300 56.3% | 169/352 48.0% |
| lastm_h >= 1 AND rest_diff <= 1 AND week_frac <= 8 -> under | 149/239 62.3% | 80/152 52.6% | 80/157 51.0% |
| rest_diff <= -1 AND total >= 5.5 AND wp_h >= 0.612 -> under | 83/126 65.9% | 50/93 53.8% | 71/141 50.4% |
| lastm_h >= 1 AND rest_h <= 2 AND week_frac <= 8 -> under | 109/170 64.1% | 57/107 53.3% | 64/130 49.2% |
| model_total_gap <= 0.128 AND pf_a <= 2.65 AND total >= 5.5 -> under | 383/639 59.9% | 150/277 54.2% | 195/400 48.8% |
| model_total_gap <= -0.0225 AND pa_a >= 2.79 AND wp_a <= 0.48 -> under | 178/287 62.0% | 135/256 52.7% | 210/423 49.6% |
| ovp_a <= 0.349 AND rest_h <= 2 AND total >= 5.5 -> under | 105/162 64.8% | 58/110 52.7% | 71/147 48.3% |
| ovp_h >= 0.5 AND rest_diff <= 0 AND wp_h <= 0.333 -> under | 124/196 63.3% | 48/86 55.8% | 60/131 45.8% |

## NHL opening line

13580 games, 106 conditions. Discovery 2011-2015, validation 2016-2018, holdout 2019-2021.

* Real data: 204 rules pass discovery, 60 also pass validation (32 distinct ideas).
* Shuffled data (20 runs, discovery->validation): median 3, 90th percentile 11, max 29 survivors.
* Distinct surviving ideas on the holdout, pooled: 10727/21206 = 50.6%.
* Every surviving rule on the holdout, each game counted once: 1311/2589 = 50.6% (by season: 2019 476/921, 2020 368/697, 2021 467/971).

| Rule | Discovery | Validation | Holdout |
|---|---|---|---|
| model_total_gap <= -0.144 AND wp_a <= 0.48 AND wp_h <= 0.476 -> under | 76/112 67.9% | 23/43 53.5% | 66/109 60.6% |
| model_total_gap <= -0.0262 AND pf_a <= 2.65 AND rest_a >= 3 -> under | 102/157 65.0% | 28/50 56.0% | 33/56 58.9% |
| pa_h >= 3.04 AND pf_a <= 2.27 AND rest_diff <= 1 -> under | 79/119 66.4% | 29/49 59.2% | 40/73 54.8% |
| lastm_h >= 1 AND ovp_h >= 0.5 AND week_frac <= 16 -> under | 175/279 62.7% | 116/211 55.0% | 105/191 55.0% |
| pa_h >= 3.04 AND pf_a <= 2.27 AND rest_a <= 3 -> under | 83/126 65.9% | 29/55 52.7% | 41/73 56.2% |
| lastm_h >= 1 AND ovp_a >= 0.5 AND week_frac <= 8 -> under | 102/157 65.0% | 65/118 55.1% | 52/96 54.2% |
| ovp_a <= 0.46 AND pa_h >= 3.04 AND pf_a <= 2.27 -> under | 71/102 69.6% | 21/40 52.5% | 31/58 53.4% |
| model_total_gap <= 0.12 AND total <= 5.5 AND total >= 5.5 -> under | 851/1500 56.7% | 260/484 53.7% | 180/347 51.9% |
| pa_a <= 2.58 AND rest_a >= 3 AND total >= 5.5 -> under | 145/230 63.0% | 61/109 56.0% | 46/94 48.9% |
| pf_a <= 2.65 AND rest_diff <= 1 AND total >= 5.5 -> under | 537/928 57.9% | 266/490 54.3% | 309/601 51.4% |
| lastm_h >= 1 AND total >= 5.5 AND week_frac <= 16 -> under | 237/385 61.6% | 171/322 53.1% | 181/348 52.0% |
| model_total_gap <= 0.12 AND rest_diff <= 1 AND total >= 5.5 -> under | 795/1381 57.6% | 580/1080 53.7% | 672/1316 51.1% |
| lastm_h >= 1 AND pf_a <= 2.65 AND total >= 5.5 -> under | 317/537 59.0% | 174/305 57.0% | 170/354 48.0% |
| lastm_a <= -2 AND ovp_h >= 0.553 AND total >= 5.5 -> under | 146/231 63.2% | 144/268 53.7% | 140/278 50.4% |
| model_total_gap <= 0.12 AND rest_a >= 1 AND total >= 5.5 -> under | 874/1545 56.6% | 634/1198 52.9% | 712/1404 50.7% |

## Verdict

| Market | Survivors (real) | Survivors (luck, avg) | Holdout, each game once |
|---|---|---|---|
| NFL closing line | 19 | 42 | 231/423 = 54.6% |
| CFB closing line | 35 | 32 | 817/1619 = 50.5% |
| CFB opening line | 76 | 27 | 840/1663 = 50.5% |
| NBA closing line | 34 | 27 | 729/1473 = 49.5% |
| NBA opening line | 10 | 23 | 1149/2247 = 51.1% |
| NHL closing line | 15 | 7 | 699/1380 = 50.7% |
| NHL opening line | 60 | 5 | 1311/2589 = 50.6% |

### Rules that also won 55%+ on the holdout (30+ bets)

* NFL closing line: neutral = 0 AND streak_h <= -1 AND wp_a <= 0.154 -> away ATS (discovery 64.8% on 165, validation 57.8% on 83, holdout 59.8% on 82)
* NFL closing line: streak_h <= -1 AND wp_a <= 0.154 -> away ATS (discovery 64.8% on 165, validation 57.1% on 84, holdout 59.8% on 82)
* NFL closing line: playoff = 0 AND streak_h <= -1 AND wp_a <= 0.154 -> away ATS (discovery 64.8% on 165, validation 57.1% on 84, holdout 59.8% on 82)
* NFL closing line: rest_diff >= -1 AND streak_h <= -1 AND wp_a <= 0.154 -> away ATS (discovery 64.9% on 154, validation 57.3% on 75, holdout 57.7% on 78)
* NFL closing line: pa_a >= 21.9 AND pa_h >= 22 AND temp <= 54 -> under (discovery 64.6% on 178, validation 53.8% on 160, holdout 60.6% on 155)
* NFL closing line: rest_h >= 6 AND streak_h <= -1 AND wp_a <= 0.154 -> away ATS (discovery 66.2% on 160, validation 56.4% on 78, holdout 57.7% on 78)
* NFL closing line: pa_a <= 19.7 AND pa_h >= 22 AND streak_a >= 3 -> over (discovery 68.3% on 101, validation 55.2% on 58, holdout 58.1% on 31)
* NFL closing line: rest_a >= 7 AND streak_h <= -1 AND wp_a <= 0.154 -> away ATS (discovery 66.9% on 151, validation 53.6% on 69, holdout 57.5% on 73)
* CFB opening line: abs_spread <= 3.5 AND model_margin_gap <= -5.58 AND rest_diff <= 0 -> away ATS (discovery 67.2% on 119, validation 63.0% on 73, holdout 59.2% on 71)
* CFB opening line: model_margin_gap <= -5.58 AND rest_a <= 8 AND spread <= 3 -> away ATS (discovery 67.2% on 125, validation 63.4% on 71, holdout 55.3% on 85)
* CFB opening line: abs_spread <= 3.5 AND dome = 0 AND model_margin_gap <= -5.58 -> away ATS (discovery 65.5% on 142, validation 58.9% on 90, holdout 58.4% on 89)
* CFB opening line: abs_spread <= 3.5 AND model_margin_gap <= -5.58 AND neutral = 0 -> away ATS (discovery 65.0% on 143, validation 58.7% on 92, holdout 58.0% on 88)
* CFB opening line: abs_spread <= 3.5 AND model_margin_gap <= -5.58 AND rest_h <= 14 -> away ATS (discovery 65.9% on 138, validation 59.3% on 91, holdout 56.8% on 88)
* CFB opening line: model_margin_gap <= -5.58 AND rest_h <= 14 AND spread <= 3 -> away ATS (discovery 64.9% on 151, validation 61.1% on 90, holdout 55.1% on 98)
* CFB opening line: atsp_a <= 0.444 AND rest_diff <= 0 AND total <= 47 -> away ATS (discovery 62.7% on 241, validation 60.9% on 115, holdout 55.2% on 134)
* CFB opening line: abs_spread <= 3.5 AND model_margin_gap <= -5.58 AND rest_a <= 14 -> away ATS (discovery 65.2% on 138, validation 58.7% on 92, holdout 56.8% on 88)
* CFB opening line: abs_spread <= 3.5 AND model_margin_gap <= -5.58 AND wp_diff <= -0.0833 -> away ATS (discovery 68.6% on 118, validation 57.4% on 68, holdout 57.4% on 68)
* CFB opening line: atsp_a <= 0.444 AND dome = 0 AND total <= 44.5 -> away ATS (discovery 65.8% on 146, validation 54.8% on 62, holdout 55.4% on 83)
* NBA closing line: abs_spread_move <= 0.5 AND atsp_a <= 0.429 AND ovp_h >= 0.56 -> away ATS (discovery 65.0% on 143, validation 57.1% on 91, holdout 61.5% on 65)
* NBA closing line: lastm_h >= 4 AND total_move <= -2 AND week_frac <= 16 -> under (discovery 66.7% on 114, validation 57.9% on 95, holdout 60.0% on 65)
* NBA closing line: streak_h >= 1 AND total_move <= -2 AND week_frac <= 16 -> under (discovery 65.4% on 133, validation 56.6% on 113, holdout 57.5% on 80)
* NBA closing line: abs_spread_move <= 0 AND model_total_gap >= 3.76 AND streak_a <= -1 -> away ATS (discovery 67.3% on 107, validation 58.1% on 43, holdout 56.0% on 50)
* NBA closing line: abs_spread_move <= 0.5 AND lastm_a <= -17 AND ovp_a >= 0.513 -> away ATS (discovery 66.7% on 120, validation 52.4% on 82, holdout 60.9% on 69)
* NBA opening line: lastm_a <= -4 AND total >= 201 AND wp_diff <= -0.208 -> away ATS (discovery 67.5% on 114, validation 54.1% on 148, holdout 55.8% on 154)
* NHL closing line: lastm_a >= 2 AND pf_a <= 2.65 AND total >= 5.5 -> under (discovery 63.9% on 183, validation 56.2% on 105, holdout 58.3% on 120)
* NHL closing line: pa_h >= 3.04 AND pf_a <= 2.27 AND total_move <= 0 -> under (discovery 65.6% on 128, validation 54.5% on 55, holdout 57.1% on 77)
* NHL opening line: model_total_gap <= -0.144 AND wp_a <= 0.48 AND wp_h <= 0.476 -> under (discovery 67.9% on 112, validation 53.5% on 43, holdout 60.6% on 109)
* NHL opening line: model_total_gap <= -0.0262 AND pf_a <= 2.65 AND rest_a >= 3 -> under (discovery 65.0% on 157, validation 56.0% on 50, holdout 58.9% on 56)
* NHL opening line: pa_h >= 3.04 AND pf_a <= 2.27 AND rest_a <= 3 -> under (discovery 65.9% on 126, validation 52.7% on 55, holdout 56.2% on 73)
