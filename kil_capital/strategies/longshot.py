"""S2 longshot_fade: favourite / optimism-tax hold (spec v4 §3.2 A).

Buy the 80-97c side (mostly NO on longshots) and hold to settlement, but only where a
calibration map fitted on TRAINING markets says the favourite wins more often than its
price plus fee:  q = g(price bucket, desk) .
"""
from __future__ import annotations

import time
from collections import defaultdict
from decimal import Decimal

from ..core import desks, money
from .base import Decision, Signal, Strategy, ask_for, last_candle_before, live_book

D = Decimal


class CalibrationMap:
    """Empirical P(win | price bucket, desk) with shrinkage toward the price itself."""

    def __init__(self, bucket=D("0.02"), prior_n=50):
        self.bucket = bucket
        self.prior_n = prior_n
        self.stats = defaultdict(lambda: [0, 0])  # key -> [wins, n]

    def key(self, p: Decimal, desk: str):
        return (desk, int(p / self.bucket))

    def add(self, p: Decimal, desk: str, won: bool):
        s = self.stats[self.key(p, desk)]
        s[0] += int(won)
        s[1] += 1

    def q(self, p: Decimal, desk: str) -> Decimal:
        w, n = self.stats.get(self.key(p, desk), (0, 0))
        return (D(w) + p * self.prior_n) / (D(n) + self.prior_n)


class LongshotFade(Strategy):
    id = "longshot_fade"
    name = "Longshot fade / favourite hold"
    catalog_id = "S2"
    evidence = "PROVEN in aggregate"
    status = "backtesting"
    is_model = True
    notes = "Negative skew: correlated tail events cluster. Interest (APY) never counts toward the verdict."

    @classmethod
    def default_params(cls):
        return {"lo": D("0.80"), "hi": D("0.97"), "min_edge": D("0.005"), "hours_before_close": 24,
                "contracts": 10}

    def variants(self):
        return [self.default_params(),
                {**self.default_params(), "lo": D("0.85")},
                {**self.default_params(), "hours_before_close": 6}]

    def __init__(self, **p):
        super().__init__(**p)
        self.cal = CalibrationMap()

    def _decision_time(self, m):
        return m["close_ts"] - self.params["hours_before_close"] * 3600

    def fit(self, train_markets):
        self.cal = CalibrationMap()
        for m in train_markets:
            t = self._decision_time(m)
            c = last_candle_before(m.get("candles", []), t)
            if not c:
                continue
            desk = desks.desk_for(m.get("series_ticker"), m.get("category"))
            for side in ("yes", "no"):
                p = ask_for(c, side)
                if p is not None and D("0") < p < D("1"):
                    self.cal.add(p, desk, m["result"] == side)

    def _pick(self, yes_bid, yes_ask, desk, fee_type="quadratic", mult=D("1")):
        lo, hi = self.params["lo"], self.params["hi"]
        best = None
        for side, p in (("yes", yes_ask), ("no", None if yes_bid is None else D("1") - yes_bid)):
            if p is None or not (lo <= p <= hi):
                continue
            try:
                f = money.fee(p, 1, fee_type=fee_type, multiplier=mult, liquidity="taker")
            except money.FeeUnknown:
                continue
            q = self.cal.q(p, desk)
            edge = q - (p + f)
            if edge >= self.params["min_edge"] and (best is None or edge > best[3]):
                best = (side, p, q, edge)
        return best

    def decisions(self, m):
        t = self._decision_time(m)
        c = last_candle_before(m.get("candles", []), t)
        if not c:
            return []
        desk = desks.desk_for(m.get("series_ticker"), m.get("category"))
        pick = self._pick(c.get("yes_bid"), c.get("yes_ask"), desk, m.get("fee_type", "quadratic"),
                          D(str(m.get("fee_multiplier", 1))))
        if not pick:
            return []
        side, p, q, edge = pick
        return [Decision(ts=t, side=side, price=p, q=q, count=int(self.params["contracts"]),
                         note=f"edge {edge:.4f}")]

    def scan(self, markets, now=None):
        now = now or time.time()
        out = []
        for m in markets:
            yb, ya = live_book(m)
            desk = desks.desk_for(m.get("series_ticker") or desks.series_of(m.get("event_ticker", "")), m.get("category"))
            pick = self._pick(yb, ya, desk)
            if pick:
                side, p, q, edge = pick
                out.append(Signal(self.id, m["ticker"], side, p, q, edge, "favourite inside band", market=m))
        return out
