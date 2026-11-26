"""Learning loop, sizing and segment tables: promotion only on unseen games, honest win-rate search."""
import random

from kil_capital.research import bigvin
from kil_capital.sports import learn, segments as SEG
from kil_capital.sports.leagues import LEAGUES

DAY = 86400


def season(n_teams=16, days=120, hfa=3.0, seed=1):
    rnd = random.Random(seed)
    strength = {f"T{i}": rnd.gauss(0, 6) for i in range(n_teams)}
    games, t0 = [], 1.7e9
    for d in range(days):
        teams = list(strength)
        rnd.shuffle(teams)
        for h, a in zip(teams[::2], teams[1::2]):
            m = strength[h] - strength[a] + hfa + rnd.gauss(0, 11)
            tot = 145 + rnd.gauss(0, 15)
            hs, as_ = round((tot + m) / 2), round((tot - m) / 2)
            games.append({"home": {"id": h, "score": hs}, "away": {"id": a, "score": as_}, "neutral": False,
                          "start_ts": t0 + d * DAY, "odds": {"spread_home": -(strength[h] - strength[a] + hfa)}})
    return games


def test_effective_applies_champion():
    lg, lam = learn.effective("cbb", {"cbb": {"hfa": 9.0, "lam": 5.0, "junk": 1}})
    assert lg.hfa == 9.0 and lam == 5.0 and lg.sigma_margin == LEAGUES["cbb"].sigma_margin


def test_promotes_only_when_challenger_wins_unseen_games():
    g = season()
    bad = {"hfa": -6.0, "halflife_days": 5.0, "lam": 50.0}           # a deliberately broken champion
    r = learn.learn_league("cbb", g, bad, grid={"hfa": [3.0], "halflife_days": [45.0], "lam": [2.0]})
    assert r["promoted"] and r["challenger_logloss"] < r["champion_logloss"] and r["holdout_n"] >= 40
    assert 0 <= r["params"]["w_model"] <= 1 and r["params"]["sigma_margin"] > 5
    same = learn.learn_league("cbb", g, r["params"], grid={"hfa": [r["params"]["hfa"]],
                              "halflife_days": [r["params"]["halflife_days"]], "lam": [r["params"]["lam"]]})
    assert not same["promoted"]                                         # a tie is not a promotion


def test_no_peeking_predictions_use_only_past_games():
    g = season(days=60)
    split = g[-1]["start_ts"] - 7 * DAY
    future = [dict(x, home=dict(x["home"], score=999)) for x in g if x["start_ts"] >= split]
    past = [x for x in g if x["start_ts"] < split]
    a = learn.predictions(LEAGUES["cbb"], 2.0, past + [x for x in g if x["start_ts"] >= split], split, split + 7 * DAY)
    b = learn.predictions(LEAGUES["cbb"], 2.0, past + future, split, split + 7 * DAY)
    assert [p["m"] for p in a] == [p["m"] for p in b]                   # results of predicted games never leak in


def test_too_few_games_is_not_promoted():
    assert not learn.learn_league("nfl", season(days=10))["promoted"]


def test_size_is_fractional_kelly_on_fee_cost_and_ranks_by_profit():
    s = SEG.size(0.60, 0.50, 1000, 500)
    c = 0.5 + SEG.taker_fee(0.5)
    assert abs(s["kelly_full"] - (0.6 - c) / (1 - c)) < 1e-4
    assert s["stake"] <= 0.25 * s["kelly_full"] * 1000 + 1e-6 and s["exp_profit"] > 0
    assert SEG.size(0.50, 0.50, 1000, 500)["count"] == 0                # no edge after fees -> no bet
    assert SEG.size(0.9, 0.5, 1e6, 50)["stake"] <= 50                   # max trade cap
    assert SEG.size(0.6, 0.5, 1000, 500, mult=0)["count"] == 0          # losing segment skipped


def picks(seg_win, n, kind="total", price=0.5, edge=0.06, t0=0):
    return [{"league": "cbb", "kind": kind, "price": price, "edge": edge, "won": i < seg_win * n, "ts": t0 + i}
            for i in range(n)]


def test_segment_table_shrinks_and_skips_losers():
    t = SEG.build_table(picks(0.40, 300, kind="spread") + picks(0.60, 20))
    lose, win = t["cbb|spread|5-10c|fav"], t["cbb|total|5-10c|fav"]
    assert lose["mult"] == 0 and lose["shrunk_roi"] > lose["roi"]
    assert 1 < win["mult"] <= 1.5 and win["shrunk_roi"] < win["roi"]   # 20 hot picks barely move it


def test_winrate_search_reports_out_of_sample_and_roi():
    rnd = random.Random(3)
    ps = [{"league": "nhl", "kind": "winner", "price": 0.80, "edge": 0.02, "won": rnd.random() < 0.70, "ts": i}
          for i in range(400)]
    s = SEG.winrate_search(ps)
    hit = s["hits"][0]
    assert hit["train_win"] >= 0.6 and hit["test_roi"] < 0 and not hit["credible"]   # 70% winner, still loses
    assert s["credible"] == []


def test_bigvin_normalise_maps_columns(tmp_path):
    (tmp_path / "a.csv").write_text("Sport,Bet_Type,Odds,Edge,Result,Date,Rank\n"
                                    "NCAAB,Over 141.5,-110,4.5,W,2026-01-02,1\n"
                                    "NBA,Spread,+120,0.03,L,2026-01-03,9\nNFL,ML,-150,2,P,2026-01-04,2\n")
    ps, skipped = bigvin.normalise(bigvin.load_rows(tmp_path))
    assert [p["league"] for p in ps] == ["cbb", "nba"] and ps[0]["kind"] == "total" and ps[1]["kind"] == "spread"
    assert abs(ps[0]["price"] - 110 / 210) < 1e-3 and ps[0]["edge"] == 0.045 and ps[0]["won"]
    assert skipped == {"push / pending / unknown result": 1}
    assert "Main reasons it loses" in bigvin.report(ps, skipped)
