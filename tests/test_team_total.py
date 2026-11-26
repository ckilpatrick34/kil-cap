"""Team totals: matched to the right team, priced from per-team points, never a pick."""
from kil_capital.sports.kalshi_games import attach, team_of
from kil_capital.sports.slate import price_contract
from kil_capital.sports.leagues import LEAGUES


def test_team_total_match_and_price():
    g = {"id": "1", "start": "2026-11-26T17:30Z", "home": {"loc": "Detroit", "short": "Lions", "name": "Detroit Lions", "nick": "Lions", "abbr": "DET"},
         "away": {"loc": "Chicago", "short": "Bears", "name": "Chicago Bears", "nick": "Bears", "abbr": "CHI"}}
    mk = {"winner": [{"ticker": "KXNFLGAME-26NOV26CHIDET-DET", "event": "KXNFLGAME-26NOV26CHIDET", "sub": "Detroit", "title": "", "strike": None, "yes_bid": .5, "yes_ask": .52, "volume": 0, "oi": 0, "close_ts": None},
                     {"ticker": "KXNFLGAME-26NOV26CHIDET-CHI", "event": "KXNFLGAME-26NOV26CHIDET", "sub": "Chicago", "title": "", "strike": None, "yes_bid": .48, "yes_ask": .5, "volume": 0, "oi": 0, "close_ts": None}],
          "team_total": [{"ticker": "KXNFLTEAMTOTAL-26NOV26CHIDET-CHI20", "event": "KXNFLTEAMTOTAL-26NOV26CHIDET", "sub": "Chicago over 20.5 points scored", "title": "", "strike": 20.5, "yes_bid": .5, "yes_ask": .53, "volume": 0, "oi": 0, "close_ts": None}]}
    out = attach("nfl", [g], mk)
    tt = out["1"]["team_total"]; assert tt[0]["team"] == "away", tt
    pr = price_contract(LEAGUES["nfl"], tt[0], {"margin": 5.0, "total": 45.0}, {"margin": 3.0, "total": 44.0}, {"margin": -1.5, "total": 44.0})
    assert 0.45 < pr["model"] < 0.49 and pr["book"] > pr["model"], pr   # CHI mean 20 vs 22.75
    assert team_of("Detroit over 24.5", g) == "home"


def test_team_total_watch_only():
    from kil_capital.sports.slate import WATCH_ONLY
    assert "team_total" in WATCH_ONLY
