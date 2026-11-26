"""Paper book + autopilot: simulated money only, off by default, never touches the venue/gateway."""
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from conftest import FakePublic
from kil_capital.api.app import create_app
from kil_capital.api.terminal import Terminal
from kil_capital.core.paper import PaperBook

LAL = "KXNBAGAME-26NOV24LALBOS-LAL"
MARKETS = [
    {"ticker": LAL, "event_ticker": "KXNBAGAME-26NOV24LALBOS", "title": "Lakers at Celtics",
     "status": "active", "yes_bid_dollars": "0.48", "yes_ask_dollars": "0.52"},
    {"ticker": "KXNCAAFGAME-26NOV28MSSTOLE-MSST", "event_ticker": "KXNCAAFGAME-26NOV28MSSTOLE",
     "title": "Mississippi State at Ole Miss", "status": "active", "yes_bid_dollars": "0.30", "yes_ask_dollars": "0.33"},
]


def opp(t, side="yes", price="0.40", edge="0.05", sid="s1"):
    return {"ticker": t, "side": side, "price": price, "edge": edge, "fair": "0.45", "strategy_id": sid, "title": t}


def test_buy_close_settle_math(tmp_path):
    b = PaperBook(tmp_path / "p.json")
    b.buy(ticker="A", side="yes", price="0.40", count=10)
    assert b.cash < D("996")                     # 4.00 + taker fee
    r = b.close("A", "0.50")
    assert D(r["pnl"]) > 0 and "A" not in b.positions
    b.buy(ticker="B", side="no", price="0.30", count=5)
    s = b.settle("B", "no")
    assert D(s["pnl"]) > D("3")                  # pays $5 on $1.50 + fee
    assert b.summary(lambda t: (None, None))["closed_trades"] == 2


def test_buy_guards(tmp_path):
    b = PaperBook(tmp_path / "p.json", start_cash=D("5"))
    with pytest.raises(ValueError):
        b.buy(ticker="A", side="yes", price="0.4", count=100)   # not enough cash
    b.buy(ticker="A", side="yes", price="0.4", count=1)
    with pytest.raises(ValueError):
        b.buy(ticker="A", side="no", price="0.4", count=1)      # opposite side


def test_autopilot_off_by_default_and_after_restart(tmp_path):
    b = PaperBook(tmp_path / "p.json")
    assert b.autopilot_step([opp("A")]) == []
    b.set_auto(enabled=True)
    assert PaperBook(tmp_path / "p.json").auto.enabled is False


def test_autopilot_respects_limits(tmp_path):
    b = PaperBook(tmp_path / "p.json")
    b.set_auto(enabled=True, max_trade_usd="10", max_total_usd="25", max_positions=5, min_edge="0.03")
    opps = [opp("LOW", edge="0.01"), opp("CHEAP", price="0.01")]
    opps += [opp(f"T{i}") for i in range(6)]
    made = b.autopilot_step(opps)
    tickers = [m["ticker"] for m in made]
    assert "LOW" not in tickers and "CHEAP" not in tickers
    risk = sum(D(p["avg_price"]) * p["count"] + D(p["fees"]) for p in b.positions.values())
    assert risk <= D("25") and len(b.positions) <= 5
    assert all(D(m["price"]) * m["count"] <= D("10") for m in made)


@pytest.fixture
def client(settings):
    T = Terminal(settings, public=FakePublic(MARKETS), start_loops=False)
    return TestClient(create_app(T, token="tok", port=8000), base_url="http://127.0.0.1:8000"), T


def test_api_paper_flow_and_no_venue_calls(client):
    c, T = client
    h = {"X-Kil-Token": "tok"}
    assert c.post("/api/paper/buy", json={"ticker": LAL, "side": "yes", "count": 3}).status_code == 403
    r = c.post("/api/paper/buy", json={"ticker": LAL, "side": "yes", "count": 3}, headers=h).json()
    assert r["price"] == "0.52" and r["count"] == 3            # priced at the server-side ask
    bad = c.post("/api/paper/buy", json={"ticker": LAL, "side": "no", "count": 1}, headers=h)  # already hold YES
    assert bad.status_code in (400, 404)
    assert c.get("/api/paper").json()["positions"][0]["ticker"] == LAL
    assert c.post("/api/autopilot", json={"enabled": True}, headers=h).status_code == 200
    T._signals_cache = {"s1": [opp(LAL, side="no", price="0.48", edge="0.10")]}
    T.paper_tick()
    assert c.post("/api/paper/close", json={"ticker": LAL}, headers=h).status_code == 200
    assert c.post("/api/paper/reset", headers=h).status_code == 200
    assert T.venue is None                                       # recommend-only: no venue exists
