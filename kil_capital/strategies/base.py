"""Strategy plugin interface (spec v4 §8.1):  accepts / fit / decisions / variants / scan / intents / info.

Registering a plugin in registry.py gives it a backtest, signals and a live gate automatically.

Backtest data: each market is a dict (see backtest/data.py) with at least
    ticker, event_ticker, series_ticker, category, title, result ('yes'|'no'),
    open_ts, close_ts, candles=[{ts, yes_bid, yes_ask, price, volume}] (dollars, point in time)
`decisions` must only look at candles with ts <= the decision time it returns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Optional

from ..core import desks
from ..core.orders import OrderIntent

D = Decimal


@dataclass
class Decision:
    ts: float                 # decision time (epoch s) -- uses data with ts <= this only
    side: str                 # side bought: yes | no
    price: Decimal            # intended limit price for that side
    liquidity: str = "taker"  # taker | maker
    count: int = 1
    q: Optional[Decimal] = None   # model probability that `side` wins (for Brier/log loss/Kelly)
    note: str = ""


@dataclass
class Signal:
    strategy_id: str
    ticker: str
    side: str
    price: Decimal
    fair: Optional[Decimal] = None
    edge: Optional[Decimal] = None
    reason: str = ""
    features: dict = field(default_factory=dict)
    market: dict = field(default_factory=dict)


class Strategy:
    id: str = "base"
    name: str = "base"
    catalog_id: str = ""          # S1, S2, ... from the spec catalog
    desk: str = "ALL"
    evidence: str = "UNPROVEN"
    status: str = "idea"          # idea | backtesting | ready for Carson's review | live
    is_model: bool = False        # has a probability model -> Brier/log loss required
    structural: bool = False      # S1/CR1: 300-event rule waived
    needs_paid_data: Optional[str] = None
    notes: str = ""
    params: dict = {}

    def __init__(self, **params):
        self.params = {**self.default_params(), **params}

    # ---- research / backtest -------------------------------------------------------
    @classmethod
    def default_params(cls) -> dict:
        return {}

    def accepts(self, market: dict) -> bool:
        return True

    def fit(self, train_markets: list[dict]) -> None:
        """Fit on training-fold markets only (settled before the test window)."""

    def decisions(self, market: dict) -> list[Decision]:
        return []

    def variants(self) -> list[dict]:
        """Parameter variants for the multiple-testing log.  Default: just the defaults."""
        return [self.default_params()]

    # ---- live / research signals --------------------------------------------------------
    def scan(self, markets: Iterable[dict], now: float) -> list[Signal]:
        return []

    def intents(self, signals: list[Signal], size_mult: Decimal = D("1")) -> list[OrderIntent]:
        out = []
        for s in signals:
            n = max(1, int(D(self.params.get("contracts", 1)) * size_mult))
            m = s.market
            t = desks.tags(m.get("series_ticker") or desks.series_of(s.ticker), m.get("category"))
            out.append(OrderIntent(ticker=s.ticker, side=s.side, action="buy", price=s.price, count=n,
                                   strategy_id=self.id, source="bot", event_ticker=m.get("event_ticker"),
                                   series_ticker=m.get("series_ticker"), q=s.fair, **t))
        return out

    def info(self) -> dict:
        return {"id": self.id, "name": self.name, "catalog_id": self.catalog_id, "desk": self.desk,
                "evidence": self.evidence, "status": self.status, "is_model": self.is_model,
                "structural": self.structural, "needs_paid_data": self.needs_paid_data,
                "notes": self.notes, "params": {k: str(v) for k, v in self.params.items()}}


# ---- shared helpers ------------------------------------------------------------------------

def last_candle_before(candles: list[dict], t: float) -> Optional[dict]:
    best = None
    for c in candles:
        if c["ts"] <= t:
            best = c
        else:
            break
    return best


def ask_for(c: dict, side: str) -> Optional[Decimal]:
    """Price to BUY `side` from a candle (yes_ask, or 1 - yes_bid for NO)."""
    if side == "yes":
        return c.get("yes_ask")
    b = c.get("yes_bid")
    return None if b is None else D("1") - b


def bid_for(c: dict, side: str) -> Optional[Decimal]:
    if side == "yes":
        return c.get("yes_bid")
    a = c.get("yes_ask")
    return None if a is None else D("1") - a


def live_book(market: dict) -> tuple[Optional[Decimal], Optional[Decimal]]:
    def g(k):
        v = market.get(f"{k}_dollars")
        if v not in (None, ""):
            return D(str(v))
        v = market.get(k)
        return None if v in (None, "") else D(str(v)) / 100
    return g("yes_bid"), g("yes_ask")
