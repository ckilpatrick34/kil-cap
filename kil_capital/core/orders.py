"""Order intent and market/portfolio snapshots shared by risk, gateway and strategies."""
from __future__ import annotations

import secrets as _pysecrets
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

D = Decimal


def new_client_order_id() -> str:
    # Not UUID-shaped on purpose so the log redactor never hides it.
    return "kil-" + _pysecrets.token_hex(10)


@dataclass
class OrderIntent:
    ticker: str
    side: str                 # "yes" | "no"
    action: str               # "buy" | "sell"
    price: Decimal            # dollars, limit price for `side`
    count: int
    strategy_id: str
    source: str = "bot"       # "bot" | "manual" | "external"
    tif: str = "gtc"          # "gtc" | "ioc" | "fok"
    post_only: bool = False
    client_order_id: str = field(default_factory=new_client_order_id)
    typed_confirmation: Optional[str] = None
    # tagging / risk metadata
    event_ticker: Optional[str] = None
    series_ticker: Optional[str] = None
    desk: Optional[str] = None
    category: Optional[str] = None
    league: Optional[str] = None
    asset: Optional[str] = None
    teams: tuple = ()
    players: tuple = ()
    cluster: Optional[str] = None          # same slate / release / crypto expiry
    settlement_source: Optional[str] = None
    q: Optional[Decimal] = None            # model / Carson fair probability for `side`
    signal_id: Optional[str] = None
    model_version: Optional[str] = None
    expected_liquidity: str = "taker"      # for the fee estimate

    def __post_init__(self):
        self.side = str(self.side).lower()
        self.action = str(self.action).lower()
        self.price = D(str(self.price))
        self.tif = str(self.tif).lower()
        if self.q is not None:
            self.q = D(str(self.q))


@dataclass
class MarketInfo:
    ticker: str
    status: str = "open"
    event_ticker: Optional[str] = None
    series_ticker: Optional[str] = None
    category: Optional[str] = None
    title: str = ""
    price_ranges: tuple = ()
    yes_bid: Optional[Decimal] = None
    yes_ask: Optional[Decimal] = None
    close_ts: Optional[float] = None       # epoch seconds
    fee_type: str = "quadratic"
    fee_multiplier: Decimal = D("1")
    strike: Optional[Decimal] = None       # for threshold markets ("above K")
    strike_direction: Optional[str] = None # "above" | "below"
    raw: dict = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.status in ("open", "active")

    def mid_for(self, side: str) -> Optional[Decimal]:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        if self.yes_bid <= 0 or self.yes_ask >= 1:
            return None
        mid = (self.yes_bid + self.yes_ask) / 2
        return mid if side == "yes" else D("1") - mid


@dataclass
class Position:
    ticker: str
    side: str                 # side held
    count: int
    avg_price: Decimal
    strategy_id: str = "external"
    source: str = "external"
    event_ticker: Optional[str] = None
    series_ticker: Optional[str] = None
    desk: Optional[str] = None
    category: Optional[str] = None
    league: Optional[str] = None
    asset: Optional[str] = None
    teams: tuple = ()
    players: tuple = ()
    cluster: Optional[str] = None
    settlement_source: Optional[str] = None
    strike: Optional[Decimal] = None
    strike_direction: Optional[str] = None
    close_ts: Optional[float] = None

    @property
    def max_loss(self) -> Decimal:
        return self.avg_price * self.count


@dataclass
class PortfolioState:
    nav: Decimal
    cash: Decimal
    start_of_day_nav: Decimal
    peak_nav: Decimal
    day_pnl: Decimal = D("0")                    # fund, realized + marked
    manual_day_pnl: Decimal = D("0")
    strategy_day_pnl: dict = field(default_factory=dict)
    positions: list = field(default_factory=list)       # list[Position]
    resting: list = field(default_factory=list)         # list[Position-like] for resting open orders
    spot: dict = field(default_factory=dict)            # asset -> spot price (crypto, index)
    spot_age_s: dict = field(default_factory=dict)
