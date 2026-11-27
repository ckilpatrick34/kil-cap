"""Per-league constants.  Sigmas are the standard deviation of the final result around the model's
expectation (well-known public figures: NFL margin ~13.5, NBA ~12, etc.).  `w_model` is how much the
blended fair price leans on our own model versus the de-vigged sportsbook line; research consistently
finds closing lines hard to beat in big markets, so the model gets less weight where books are sharpest.

NFL totals get no model weight at all (w_total=0): on 2,992 games from 2012-2025 the closing total missed by
10.48 points on average and our best total by 10.81, and betting our side of the gap lost at every size
(3+ points: 48% on 910 bets).  The Kil Cap total is still shown, as a reference, not a signal."""
from dataclasses import dataclass


@dataclass(frozen=True)
class League:
    key: str
    name: str
    path: str                 # ESPN site API path
    series: tuple             # Kalshi (game, spread, total) series
    sigma_margin: float
    sigma_total: float
    hfa: float                # home edge in points (goals for NHL)
    blowout_cap: float        # cap on margins when fitting ratings
    season_start: str         # YYYY-MM-DD; history is fetched from here
    halflife_days: float      # recency weighting of past games
    w_model: float
    outdoor: bool = False
    groups: str | None = None
    b2b_penalty: float = 0.0  # playing the day after another game
    lam_total: float = 2.0    # ridge on the offence/defence scoring ratings.  Margin's ridge is far too weak here:
                              # at 1-2 a team's few games swing its total by 10+ points and the projection is
                              # worse than the league average.  Values below minimise walk-forward error.
    w_total: float | None = None  # model weight for totals; None = w_model


LEAGUES = {l.key: l for l in [
    League("nfl", "NFL", "football/nfl", ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL"),
           13.5, 10.0, 1.6, 28, "2026-09-08", 70, 0.35, outdoor=True, lam_total=12.0, w_total=0.0),
    League("nba", "NBA", "basketball/nba", ("KXNBAGAME", "KXNBASPREAD", "KXNBATOTAL"),
           12.0, 18.0, 2.0, 30, "2026-10-19", 45, 0.35, b2b_penalty=1.5, lam_total=8.0),
    League("cfb", "College football", "football/college-football",
           ("KXNCAAFGAME", "KXNCAAFSPREAD", "KXNCAAFTOTAL"), 15.5, 13.0, 2.5, 28, "2026-08-27", 70, 0.45,
           outdoor=True, groups="80", lam_total=4.0),
    League("cbb", "College basketball", "basketball/mens-college-basketball",
           ("KXNCAAMBGAME", "KXNCAAMBSPREAD", "KXNCAAMBTOTAL"), 11.0, 16.0, 3.0, 25, "2026-11-01", 45, 0.45,
           groups="50", b2b_penalty=1.0, lam_total=8.0),
    League("nhl", "NHL", "hockey/nhl", ("KXNHLGAME", "KXNHLSPREAD", "KXNHLTOTAL"),
           2.4, 2.3, 0.15, 5, "2026-10-05", 45, 0.30, b2b_penalty=0.2, lam_total=20.0),
]}

# Kalshi team-total series (ladders like "Chicago over 20.5 points").  Watch-only until the track record shows a profit.
TEAM_TOTAL = {"nfl": "KXNFLTEAMTOTAL", "nba": "KXNBATEAMTOTAL", "cfb": "KXNCAAFTEAMTOTAL", "cbb": "KXNCAAMBTEAMTOTAL"}

SERIES_TO_LEAGUE = {s: (l.key, i) for l in LEAGUES.values() for i, s in enumerate(l.series)}
