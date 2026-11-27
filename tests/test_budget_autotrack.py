from kil_capital.autotrack import AutoTrack, fee
from kil_capital.budget import allocate
from kil_capital.sports import calibrate as CAL


def pick(t, fair=0.6, price=0.5, edge=0.08, **kw):
    return {"ticker": t, "side": "yes", "fair": fair, "price": price, "edge": edge, "exp_profit": 1.0,
            "slate": True, "start": "2099-01-01T00:00:00Z", **kw}


def test_allocate_respects_budget_and_max_bet():
    out = allocate([pick(f"T{i}") for i in range(20)], 100, 25, 3)
    on = [p for p in out if p["slate"]]
    assert on and all(p["stake"] <= 3 for p in on)
    assert sum(p["stake"] for p in on) <= 25
    assert any(not p["slate"] for p in out)            # the rest are watch-only


def test_nfl_bets_capped_at_five_dollars():
    out = allocate([pick("N", fair=0.8, league="NFL"), pick("B", fair=0.8, league="NBA")], 100, 100, 10)
    by = {p["ticker"]: p for p in out}
    assert 0 < by["N"]["stake"] <= 5 < by["B"]["stake"] <= 10


def test_fee_rounds_up_to_cent():
    assert fee(1, 0.5) == 0.02 and fee(10, 0.5) == 0.18


class Pub:
    def __init__(self, res): self.res = res
    def market(self, t): return {"result": self.res}


def test_autotrack_enters_once_grades_and_summarises(tmp_path):
    a = AutoTrack(tmp_path / "a.json", 100, 25, 3)
    assert a.enter([pick("A"), pick("B")], "v1") == 2
    assert a.enter([pick("A")], "v1") == 0               # one entry per ticker, ever
    assert a.open_risk() <= 25
    a.mark({"A": 0.6, "B": 0.6})
    for b in a.bets:
        b["start"] = "2000-01-01T00:00:00Z"
    assert a.grade(Pub("yes")) == 2
    s = a.summary()
    assert s["total"]["w"] == 2 and s["total"]["pnl"] > 0 and s["total"]["avg_clv"] == 0.1
    assert s["by"]["side"][0]["key"] == "favourite"


def test_calibration_promotes_only_on_holdout_gain():
    # model is pure noise around the market: shrinking toward the mid should win
    rows = [{"model_fair": 0.9 if i % 2 else 0.1, "mid": 0.5, "won": i % 3 == 0, "ts": i} for i in range(200)]
    res = CAL.fit(rows, 0.5)
    assert res["promoted"] and res["w"] < 0.5
    assert not CAL.fit(rows[:10], 0.5)["promoted"]       # too few graded picks


def test_allocate_can_keep_underdogs_watch_only():
    from kil_capital.budget import FAVOURITE, allocate
    ps = [{"ticker": "FAV", "fair": 0.7, "price": 0.6, "edge": 0.06}, {"ticker": "DOG", "fair": 0.4, "price": 0.3, "edge": 0.06}]
    got = {p["ticker"]: p["slate"] for p in allocate(ps, 100, 25, 3, FAVOURITE)}
    assert got == {"FAV": True, "DOG": False}
    assert all(p["slate"] for p in allocate(ps, 100, 25, 3))
