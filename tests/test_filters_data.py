from kil_capital import publish
from kil_capital.sports.espn import parse_event


def _ev(rank_home, rank_away, conf_home):
    comp = lambda side, rank, conf, abbr: {"homeAway": side, "curatedRank": {"current": rank},
                                          "team": {"id": abbr, "displayName": abbr, "abbreviation": abbr,
                                                   "conferenceId": conf}}
    return {"id": "1", "date": "2026-11-28T20:00Z", "competitions": [{"competitors": [
        comp("home", rank_home, conf_home, "UGA"), comp("away", rank_away, "5", "OSU")]}]}


def test_rank_and_conference_parsed():
    g = parse_event(_ev(3, 99, "8"), "cfb")
    assert (g["home"]["rank"], g["home"]["conf"]) == (3, "SEC")
    assert (g["away"]["rank"], g["away"]["conf"]) == (None, "Big Ten")   # 99 = unranked
    assert parse_event(_ev(3, 99, "999"), "cfb")["home"]["conf"] is None  # unknown id: no guess


def test_picks_carry_teams_and_market_type():
    games = [{"id": "g1", "home": {"name": "Georgia", "abbr": "UGA", "rank": 3, "conf": "SEC"},
              "away": {"name": "Ohio State", "abbr": "OSU", "rank": None, "conf": "Big Ten"}}]
    ps = publish._enrich([{"ticker": "KXNCAAFSPREAD-26NOV28OSUUGA-UGA7", "game_id": "g1"},
                          {"ticker": "KXBTCD-X", "desk": "crypto"}], games)
    assert ps[0]["kind"] == "spread" and ps[0]["teams"][1]["conf"] == "SEC" and ps[0]["teams"][1]["rank"] == 3
    assert ps[1]["kind"] == "crypto" and ps[1]["teams"] == []
