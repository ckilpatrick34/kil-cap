"""elo_sports: Elo game model on Kalshi game markets.

Spec v4: NEGATIVE so far (OOS -24.9% on 48 events, model Brier worse than market).
Recommendation: retire as a stand-alone strategy and keep Elo only as a prior/feature for X1/X3
(open question §12 Q10).  Kept registered so its report stays visible.
"""
from __future__ import annotations

from decimal import Decimal

from ..core import desks, money
from .base import Decision, Strategy, ask_for, last_candle_before

D = Decimal


class EloSports(Strategy):
    id = "elo_sports"
    name = "Elo game model"
    catalog_id = "-"
    evidence = "NEGATIVE so far"
    status = "backtesting"
    is_model = True
    notes = "Recommend retiring as stand-alone (spec §12 Q10). Keep Elo as a feature for X1/X3."

    @classmethod
    def default_params(cls):
        return {"k": 20, "min_edge": D("0.03"), "hours_before_close": 3, "contracts": 5}

    def __init__(self, **p):
        super().__init__(**p)
        self.r: dict[str, float] = {}

    def accepts(self, m):
        return desks.desk_for(m.get("series_ticker"), m.get("category")) in desks.SPORTS_DESKS \
            and "GAME" in (m.get("series_ticker") or "").upper()

    def _q(self, team, opp) -> float:
        rt, ro = self.r.get(team, 1500.0), self.r.get(opp, 1500.0)
        return 1.0 / (1.0 + 10 ** ((ro - rt) / 400.0))

    def fit(self, train):
        self.r = {}
        seen = set()
        for m in sorted(train, key=lambda x: x["close_ts"]):
            if not self.accepts(m) or m.get("event_ticker") in seen:
                continue
            team, opp = m.get("yes_sub_title"), m.get("opponent")
            if not team or not opp:
                continue
            seen.add(m.get("event_ticker"))
            q = self._q(team, opp)
            s = 1.0 if m["result"] == "yes" else 0.0
            k = self.params["k"]
            self.r[team] = self.r.get(team, 1500.0) + k * (s - q)
            self.r[opp] = self.r.get(opp, 1500.0) - k * (s - q)

    def decisions(self, m):
        if not self.accepts(m):
            return []
        team, opp = m.get("yes_sub_title"), m.get("opponent")
        if not team or not opp or team not in self.r or opp not in self.r:
            return []
        t = m["close_ts"] - self.params["hours_before_close"] * 3600
        c = last_candle_before(m.get("candles", []), t)
        if not c:
            return []
        qy = D(str(round(self._q(team, opp), 4)))
        for side, q in (("yes", qy), ("no", D("1") - qy)):
            p = ask_for(c, side)
            if p is None or not (D("0") < p < D("1")):
                continue
            f = money.fee(p, 1, fee_type=m.get("fee_type", "quadratic"), multiplier=D(str(m.get("fee_multiplier", 1))),
                          liquidity="taker")
            if q - p - f >= self.params["min_edge"]:
                return [Decision(ts=t, side=side, price=p, q=q, count=int(self.params["contracts"]))]
        return []
