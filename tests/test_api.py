import pytest
from fastapi.testclient import TestClient

from conftest import FakePublic
from kil_capital.api.app import create_app
from kil_capital.api.terminal import Terminal

MARKETS = [
    {"ticker": "KXNBAGAME-26NOV24LALBOS-LAL", "event_ticker": "KXNBAGAME-26NOV24LALBOS", "title": "Lakers at Celtics",
     "status": "active", "yes_bid_dollars": "0.48", "yes_ask_dollars": "0.52"},
    {"ticker": "KXNCAAFGAME-26NOV28MSSTOLE-MSST", "event_ticker": "KXNCAAFGAME-26NOV28MSSTOLE",
     "title": "Mississippi State at Ole Miss", "status": "active", "yes_bid_dollars": "0.30", "yes_ask_dollars": "0.33"},
]


@pytest.fixture
def client(settings):
    T = Terminal(settings, public=FakePublic(MARKETS), start_loops=False)
    app = create_app(T, token="tok", port=8000)
    return TestClient(app, base_url="http://127.0.0.1:8000"), T


def test_index_and_status(client):
    c, T = client
    assert "tok" in c.get("/").text
    s = c.get("/api/status").json()
    assert s["mode"] == "RECOMMEND-ONLY" and "credentials" not in s


def test_token_required_for_state_change(client):
    c, _ = client
    assert c.post("/api/paper/reset").status_code == 403
    assert c.post("/api/paper/reset", headers={"X-Kil-Token": "tok"}).status_code == 200


def test_bad_host_and_origin(client):
    c, _ = client
    assert c.get("/api/status", headers={"host": "evil.com"}).status_code == 403
    r = c.post("/api/paper/reset", headers={"X-Kil-Token": "tok", "origin": "http://evil.com"})
    assert r.status_code == 403


def test_scanner_hides_msu(client):
    c, _ = client
    tickers = [m["ticker"] for m in c.get("/api/markets").json()["markets"]]
    assert tickers == ["KXNBAGAME-26NOV24LALBOS-LAL"]
    assert c.get("/api/markets/KXNCAAFGAME-26NOV28MSSTOLE-MSST").status_code == 404


def test_recommend_only_no_order_or_live_endpoints(client):
    """Kalshi order placement is removed: every order, kill and go-live route is gone and nothing holds a venue."""
    c, T = client
    h = {"X-Kil-Token": "tok"}
    body = {"ticker": "KXNBAGAME-26NOV24LALBOS-LAL", "side": "yes", "price": "0.50", "count": 1}
    for path in ("/api/orders", "/api/orders/preview", "/api/orders/cancel_all", "/api/kill",
                 "/api/strategies/pm_carson/live"):
        assert c.post(path, json=body, headers=h).status_code in (404, 405), path
    assert T.venue is None and not hasattr(T, "gateway")
    assert c.get("/api/status").json()["mode"] == "RECOMMEND-ONLY"


def test_limits_tighten_only_api(client):
    c, _ = client
    h = {"X-Kil-Token": "tok"}
    assert c.put("/api/risk/limits", json={"changes": {"max_order_contracts": 100}}, headers=h).status_code == 200
    assert c.put("/api/risk/limits", json={"changes": {"max_order_contracts": 1000}}, headers=h).status_code == 400


def test_audit_endpoint_chain_ok(client):
    c, _ = client
    assert c.get("/api/audit").json()["chain_ok"]


def test_misc_endpoints(client):
    c, _ = client
    for p in ("/api/health", "/api/tick", "/api/risk", "/api/strategies", "/api/backtests", "/api/pnl",
              "/api/positions", "/api/fills", "/api/orders", "/api/pm/picks",
              "/api/strategies/longshot_fade/signals", "/api/markets/KXNBAGAME-26NOV24LALBOS-LAL/book"):
        assert c.get(p).status_code == 200, p
