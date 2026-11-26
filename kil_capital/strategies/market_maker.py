"""C6 market_maker: two-sided maker (proxy backtest).

Evidence is MIXED: MLB makers realized -7.39c (adverse selection, Moulinier).  Maker fees on
game series eat thin spreads.  Backtest fills only on a STRICT trade-through of our price.
"""
from __future__ import annotations

from decimal import Decimal

from .base import Decision, Strategy, last_candle_before

D = Decimal


class MarketMaker(Strategy):
    id = "market_maker"
    name = "Two-sided maker (proxy)"
    catalog_id = "C6"
    evidence = "MIXED (adverse selection on MLB)"
    status = "backtesting"
    notes = "Queue position unknown in backtests; candle trade-through is a proxy. No sharp-line pull yet."

    @classmethod
    def default_params(cls):
        return {"min_spread": D("0.04"), "hours_before_close": 12, "contracts": 5}

    def decisions(self, m):
        t = m["close_ts"] - self.params["hours_before_close"] * 3600
        c = last_candle_before(m.get("candles", []), t)
        if not c or c.get("yes_bid") is None or c.get("yes_ask") is None:
            return []
        yb, ya = c["yes_bid"], c["yes_ask"]
        if ya - yb < self.params["min_spread"] or yb <= 0 or ya >= 1:
            return []
        tick = D("0.01")
        n = int(self.params["contracts"])
        return [Decision(ts=t, side="yes", price=yb + tick, liquidity="maker", count=n, note="bid+1"),
                Decision(ts=t, side="no", price=(D("1") - ya) + tick, liquidity="maker", count=n, note="ask-1")]
