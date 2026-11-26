"""Sports model, Kalshi game matching, crypto pricing/backtests and the new endpoints, all on synthetic data."""
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import FakePublic
from kil_capital.api.app import create_app
from kil_capital.api.terminal import Terminal
from kil_capital.core.paper import PaperBook
from kil_capital.crypto import backtest as BT
from kil_capital.crypto import indicators as I
from kil_capital.crypto.kalshi_crypto import p_above, price_markets
from kil_capital.sports import model as M
from kil_capital.sports.kalshi_games import attach, event_date, norm
from kil_capital.sports.leagues import LEAGUES
from kil_capital.sports.ratings import fit

NBA = LEAGUES["nba"]
NOW = datetime(2026, 11, 25, tzinfo=timezone.utc).timestamp()


def team(i, abbr, loc, nick):
    return {"id": i, "abbr": abbr, "loc": loc, "nick": nick, "short": nick, "name": f"{loc} {nick}", "score": None}


def season(strength, n_rounds=12, seed=1):
    """Round-robin with true margins = strength diff + home edge + noise."""
    rnd = random.Random(seed)
    ids, games = list(strength), []
    for r in range(n_rounds):
        for h in ids:
            for a in ids:
                if h == a:
                    continue
                m = strength[h] - strength[a] + 2 + rnd.gauss(0, 6)
                games.append({"home": {"id": h, "score": 110 + m / 2}, "away": {"id": a, "score": 110 - m / 2},
                              "neutral": False, "start_ts": NOW - 86400 * (r + 1)})
    return games


# ---------------- sports model ----------------
def test_ratings_recover_true_order():
    R = fit(NBA, season({"A": 8, "B": 0, "C": -8}), NOW)
    assert R.margin["A"] > R.margin["B"] > R.margin["C"]
    assert R.margin["A"] - R.margin["C"] == pytest.approx(16, abs=5)


def test_probabilities_are_sane():
    assert M.p_home_win(NBA, 0) == pytest.approx(0.5)
    assert M.p_home_win(NBA, 10) > 0.75
    assert M.p_cover(5, 5, 12) == pytest.approx(0.5)
    assert M.p_over(220, 210, 18) > 0.5 > M.p_over(200, 210, 18)
    assert M.devig(-150, 130) == pytest.approx(0.587, abs=0.01)
    bv = M.book_view(NBA, {"spread_home": -4.5, "total": 221, "ml_home": -180, "ml_away": 150})
    assert bv["margin"] == 4.5 and bv["total"] == 221 and bv["p_home"] > 0.6
    b = M.blend(NBA, {"margin": 10, "total": 230}, bv)
    assert 4.5 < b["margin"] < 10 and 221 < b["total"] < 230


def test_project_uses_ratings():
    R = fit(NBA, season({"A": 8, "B": -8}), NOW)
    g = {"home": team("A", "AAA", "Alpha", "Ants"), "away": team("B", "BBB", "Beta", "Bees"),
         "neutral": False, "start_ts": NOW + 86400}
    p = M.project(NBA, g, R)
    assert p["margin"] > 10 and p["games_played"] > 5
    assert M.project(NBA, {**g, "home": team("Z", "ZZZ", "Zed", "Zs")}, R) is None


# ---------------- Kalshi game matching ----------------
def q(ticker, ev, sub, strike=None, title=""):
    return {"ticker": ticker, "event": ev, "sub": sub, "title": title, "strike": strike,
            "yes_bid": 0.45, "yes_ask": 0.48, "volume": 900, "oi": 0, "close_ts": None}


def test_attach_pins_winner_spread_total():
    g = {"id": "g1", "start": "2026-11-27T00:30Z",     # 7:30pm ET on Nov 26
         "home": team("1", "BOS", "Boston", "Celtics"), "away": team("2", "LAL", "Los Angeles", "Lakers")}
    ev = "KXNBAGAME-26NOV26LALBOS"
    mk = {"winner": [q(ev + "-BOS", ev, "Boston"), q(ev + "-LAL", ev, "Los Angeles L")],
          "spread": [q("KXNBASPREAD-26NOV26LALBOS-BOS5", "KXNBASPREAD-26NOV26LALBOS", "Boston wins by over 5.5 points", 5.5)],
          "total": [q("KXNBATOTAL-26NOV26LALBOS-220", "KXNBATOTAL-26NOV26LALBOS", "Over 220.5", 220.5)]}
    out = attach("nba", [g], mk)["g1"]
    assert {c["team"] for c in out["winner"]} == {"home", "away"}
    assert out["spread"][0]["team"] == "home" and out["spread"][0]["line"] == 5.5
    assert out["total"][0]["line"] == 220.5
    assert event_date(ev).isoformat() == "2026-11-26"
    assert norm("St. John's") == "state john s"


def test_attach_ignores_wrong_date():
    g = {"id": "g1", "start": "2026-11-29T00:30Z", "home": team("1", "BOS", "Boston", "Celtics"),
         "away": team("2", "LAL", "Los Angeles", "Lakers")}
    ev = "KXNBAGAME-26NOV26LALBOS"
    assert attach("nba", [g], {"winner": [q(ev + "-BOS", ev, "Boston"), q(ev + "-LAL", ev, "Los Angeles L")]}) == {}


# ---------------- crypto indicators / backtests ----------------
def walk(n=900, drift=0.001, vol=0.03, seed=3):
    rnd, x, out = random.Random(seed), 100.0, []
    for _ in range(n):
        x *= math.exp(drift + rnd.gauss(0, vol))
        out.append(x)
    return out


def test_indicators():
    assert I.sma([1, 2, 3, 4], 2)[-1] == pytest.approx(3.5)
    up = [float(i) for i in range(1, 40)]
    assert I.rsi(up)[-1] > 90
    assert I.rsi(up[::-1])[-1] < 10
    v = I.ewma_vol(I.log_returns(walk(vol=0.02)))
    assert 0.01 < (v[-1] if isinstance(v, list) else v) < 0.04


def test_backtest_buy_hold_matches_price_change():
    c = walk()
    r = BT.run(c, [1.0] * len(c), fee=0)
    total = r["total"] if "total" in r else math.prod(1 + x for x in r["rets"]) - 1
    assert total == pytest.approx(c[-1] / c[0] - 1, rel=1e-6)


def test_verdict_rules():
    bh = {"sharpe": 0.8, "max_dd": 0.6}
    good = {"in_sample": {"sharpe": 1.2}, "out_of_sample": {"sharpe": 1.0, "max_dd": 0.3}, "trades": 40, "luck_p": 0.02}
    assert BT.verdict(good, bh) == "keep"
    assert BT.verdict({**good, "luck_p": 0.4}, bh) == "watch"
    assert BT.verdict({**good, "trades": 5}, bh) == "watch"
    assert BT.verdict({**good, "out_of_sample": {"sharpe": 0.1, "max_dd": 0.3}}, bh) == "drop"


def test_luck_p_is_high_for_random_positions():
    c = walk(drift=0.0)
    pos = [random.Random(9).choice([0.0, 1.0]) for _ in c]
    r = BT.run(c, pos)
    s = BT.metrics(r["rets"])["sharpe"] if "rets" in r else 0
    assert BT.luck_p(c, pos, s, BT.FEE_PER_SIDE) > 0.05


# ---------------- Kalshi crypto pricing ----------------
def test_p_above_monotone_and_bounded():
    a, b = p_above(100_000, 95_000, 24, 0.006), p_above(100_000, 105_000, 24, 0.006)
    assert 1 > a > 0.5 > b > 0
    assert p_above(100_000, 99_000, 0, 0.006) == 1.0


def test_price_markets_flags_mispriced_contract():
    exp = (datetime.fromtimestamp(NOW, timezone.utc) + timedelta(hours=12)).isoformat()
    cheap = {"ticker": "KXBTC-X-B1", "strike_type": "greater", "floor_strike": 90_000, "close_time": exp,
             "yes_bid_dollars": "0.55", "yes_ask_dollars": "0.58"}
    fair = {**cheap, "ticker": "KXBTC-X-B2", "floor_strike": 100_000, "yes_bid_dollars": "0.48", "yes_ask_dollars": "0.52"}
    rows = {r["ticker"]: r for r in price_markets([cheap, fair], 100_000, 0.006, now=NOW)}
    assert rows["KXBTC-X-B1"]["tradeable"] and rows["KXBTC-X-B1"]["best"]["side"] == "yes"
    assert not rows["KXBTC-X-B2"]["tradeable"]


# ---------------- autopilot respects the model's size ----------------
def test_autopilot_caps_at_signal_count(tmp_path):
    b = PaperBook(tmp_path / "p.json")
    b.set_auto(enabled=True, max_trade_usd="50", max_total_usd="200")
    made = b.autopilot_step([{"ticker": "T", "side": "yes", "price": "0.40", "edge": "0.08", "fair": "0.50",
                              "strategy_id": "game_model", "count": 3}])
    assert len(made) == 1 and b.positions["T"]["count"] == 3


# ---------------- endpoints ----------------
@pytest.fixture
def client(settings):
    T = Terminal(settings, public=FakePublic([]), start_loops=False)
    return TestClient(create_app(T, token="tok", port=8000), base_url="http://127.0.0.1:8000"), T


def test_slate_and_crypto_endpoints(client):
    c, T = client
    T.slate.state = {"updated": "x", "errors": [], "ratings_n": {}, "signals": [{"ticker": "A"}],
                     "games": [{"id": "g1", "contracts": [{"ticker": "A", "tradeable": True}, {"ticker": "B"}]}]}
    s = c.get("/api/slate").json()
    assert s["games"][0]["n_contracts"] == 2 and s["games"][0]["n_trades"] == 1 and "contracts" not in s["games"][0]
    assert c.get("/api/slate/game/g1").json()["contracts"][0]["ticker"] == "A"
    assert c.get("/api/slate/game/nope").status_code == 404
    assert c.get("/api/crypto").status_code == 200


def test_refresh_needs_token(client, monkeypatch):
    c, T = client
    monkeypatch.setattr(T, "refresh_slate", lambda: None)
    monkeypatch.setattr(T, "refresh_crypto", lambda: None)
    assert c.post("/api/refresh").status_code in (401, 403)
    assert c.post("/api/refresh", headers={"X-Kil-Token": "tok"}).status_code == 200


def test_index_serves_v3_with_token(client):
    c, _ = client
    html = c.get("/").text
    assert "/static/v3.js" in html and "__KIL_TOKEN__" not in html
