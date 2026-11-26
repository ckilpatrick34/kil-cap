import time
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

import pytest

from kil_capital.config import Settings
from kil_capital.core.orders import MarketInfo, OrderIntent, PortfolioState


class FakePublic:
    """Stands in for venue.public.PublicClient (no network)."""
    last_ok = time.time()
    last_error = None

    def __init__(self, markets=None):
        self.markets_by_ticker = {m["ticker"]: m for m in (markets or [])}

    def market(self, t):
        return self.markets_by_ticker.get(t, {"ticker": t, "status": "active", "title": t,
                                              "yes_bid_dollars": "0.48", "yes_ask_dollars": "0.52"})

    def market_info(self, t):
        from kil_capital.venue.public import market_info
        return market_info(self.market(t), {"fee_type": "quadratic", "fee_multiplier": 1})

    def markets(self, **kw):
        from kil_capital.core import blocklist
        return blocklist.filter_markets(list(self.markets_by_ticker.values())), None

    def series(self, s):
        return {"ticker": s, "fee_type": "quadratic", "fee_multiplier": 1}

    def orderbook(self, t, depth=20):
        return {"yes_dollars": [["0.48", "10"]], "no_dollars": [["0.48", "10"]]}

    def trades(self, t, **kw):
        return {"trades": []}

    def candles(self, *a, **kw):
        return []


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    return replace(s, data_dir=tmp_path / "data", reports_dir=tmp_path / "reports",
                   mlb_model_dir=tmp_path / "mlb")


def open_market(ticker="KXNBAGAME-26NOV24LALBOS-LAL", bid="0.48", ask="0.52", **kw):
    return MarketInfo(ticker=ticker, status="active", event_ticker=ticker.rsplit("-", 1)[0],
                      series_ticker=ticker.split("-")[0], title=kw.pop("title", "Lakers at Celtics"),
                      yes_bid=D(bid), yes_ask=D(ask), close_ts=time.time() + 86400, **kw)


def pf(nav="10000", **kw):
    n = D(nav)
    return PortfolioState(nav=n, cash=n, start_of_day_nav=n, peak_nav=n, **kw)


def order(**kw):
    base = dict(ticker="KXNBAGAME-26NOV24LALBOS-LAL", side="yes", action="buy", price=D("0.50"), count=10,
                strategy_id="longshot_fade")
    base.update(kw)
    return OrderIntent(**base)
