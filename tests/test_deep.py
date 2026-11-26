import random

from kil_capital.research import deep, features


def _rows(seasons=12, per=180, seed=1):
    rnd, teams, rows, ts = random.Random(seed), [f"T{i}" for i in range(16)], [], 0
    power = {t: rnd.gauss(0, 5) for t in teams}
    for s in range(2000, 2000 + seasons):
        for _ in range(per):
            h, a = rnd.sample(teams, 2)
            exp = power[h] - power[a] + 2
            m = round(exp + rnd.gauss(0, 13))
            ts += 86400
            rows.append({"id": str(ts), "league": "x", "season": s, "ts": ts, "week": 1, "playoff": False,
                         "home": h, "away": a, "hs": 20.0 + max(m, 0), "as_": 20.0 + max(-m, 0),
                         "neutral": False, "spread": exp, "total": 40.0 + abs(m) * 0 + rnd.gauss(0, 1),
                         "rest_h": 7, "rest_a": 7, "div": False, "dome": False, "temp": None, "wind": None,
                         "qb_h": None, "qb_a": None})
    return rows


def test_features_are_point_in_time():
    rows = _rows(seasons=2, per=60)
    X1, _ = features.build(rows)
    rows[-1] = {**rows[-1], "hs": 99.0}            # change only the last result
    X2, _ = features.build(rows)
    assert X1 == X2                                # no row's features may depend on its own or later results


def test_efficient_market_is_not_beaten():
    r = deep.run(_rows(), "x", first_test=2004)    # closing line = true expectation, so no real edge exists
    assert "gbm" not in r["markets"]["spread"]["promoted"]
    assert r["markets"]["spread"]["models"]["gbm"]["rmse_late"] >= r["markets"]["spread"]["market_rmse_late"] - 0.01


def test_devig_removes_margin():
    p = features.devig(-110, -110)
    assert abs(p - 0.5) < 1e-9
    assert features.devig(None, 120) is None


def test_ml_bets_pays_real_odds():
    import numpy as np
    meta = [{"ml_h": 150.0, "ml_a": -170.0}, {"ml_h": 150.0, "ml_a": -170.0}]
    win = np.array([1.0, 0.0])
    p_hat = np.array([0.6, 0.6])                    # model likes the +150 home side in both games
    b = deep.ml_bets(p_hat, meta, win, np.array([True, True]), 0.0)
    assert b["n"] == 2 and b["wins"] == 1 and abs(b["roi"] - (1.5 - 1) / 2) < 1e-9


def test_impossible_moneylines_rejected():
    from kil_capital.research import sources
    assert not sources._ml_ok(-145.0, -152.0)       # both favoured: 119% implied
    assert not sources._ml_ok(-110.0, 125.0)        # under 100%: an arbitrage, so a bad row
    assert sources._ml_ok(-110.0, -110.0)
