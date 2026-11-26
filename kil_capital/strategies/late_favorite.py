"""Late-favourite family (spec v4 §3.2): S6 sports, S4 weather (late-day), CR2 crypto.

Buy the leading side inside a price band in the final window before the market's
*expected* expiration.  Uses `expected_expiration_ts` when present because close_time can be
early-close-able (§6.1: no close_time as a clock on markets that can close early).
Crypto: never inside the final 60 s averaging window (§4.4).
"""
from __future__ import annotations

import time
from decimal import Decimal

from ..core import desks
from .base import Decision, Signal, Strategy, ask_for, last_candle_before, live_book

D = Decimal


class LateFavorite(Strategy):
    desk_filter: tuple = ()
    window_s: int = 600
    guard_s: int = 0

    @classmethod
    def default_params(cls):
        return {"lo": D("0.60"), "hi": D("0.90"), "contracts": 5}

    def accepts(self, m):
        return desks.desk_for(m.get("series_ticker"), m.get("category")) in self.desk_filter

    def _expiry(self, m):
        return m.get("expected_expiration_ts") or m["close_ts"]

    def decisions(self, m):
        if not self.accepts(m):
            return []
        exp = self._expiry(m)
        t = exp - self.window_s
        c = last_candle_before(m.get("candles", []), t)
        if not c:
            return []
        for side in ("yes", "no"):
            p = ask_for(c, side)
            if p is not None and self.params["lo"] <= p <= self.params["hi"]:
                return [Decision(ts=t, side=side, price=p, count=int(self.params["contracts"]),
                                 note="late leader")]
        return []

    def scan(self, markets, now=None):
        now = now or time.time()
        out = []
        for m in markets:
            if not self.accepts(m):
                continue
            from ..venue.public import _ts
            exp = _ts(m.get("expected_expiration_time")) or _ts(m.get("close_time"))
            if not exp or not (self.guard_s < exp - now <= self.window_s):
                continue
            yb, ya = live_book(m)
            for side, p in (("yes", ya), ("no", None if yb is None else D("1") - yb)):
                if p is not None and self.params["lo"] <= p <= self.params["hi"]:
                    out.append(Signal(self.id, m["ticker"], side, p, None, None, "late leader", market=m))
                    break
        return out


class LateFavoriteSports(LateFavorite):
    id = "late_favorite_sports"
    name = "Late-game leader (sports)"
    catalog_id = "S6"
    evidence = "PLAUSIBLE"
    status = "backtesting"
    desk_filter = ("MLB", "NBA", "NFL", "NHL", "CFB", "CBB", "SPORTS-OTHER")
    window_s = 600
    notes = "Needs play-by-play game clock for a true backtest; candle proxy uses expected expiration."


class LateFavoriteWeather(LateFavorite):
    id = "late_favorite_weather"
    name = "Late-day weather favourite (S4 proxy)"
    catalog_id = "S4"
    evidence = "PLAUSIBLE (observation subset only)"
    status = "backtesting"
    desk_filter = ("WEATHER",)
    window_s = 6 * 3600
    notes = "The real S4 needs IEM ASOS observations (obs model not built yet). Forecasting is NEGATIVE."

    @classmethod
    def default_params(cls):
        return {"lo": D("0.85"), "hi": D("0.97"), "contracts": 5}


class LateFavoriteCrypto(LateFavorite):
    id = "late_favorite_crypto"
    name = "Late favourite (crypto)"
    catalog_id = "CR2"
    evidence = "PLAUSIBLE"
    status = "backtesting"
    desk_filter = ("CRYPTO",)
    window_s = 3600
    guard_s = 120   # stay clear of the final 60 s averaging window (plus margin)
    notes = "Gap risk: BTC can move through a strike in minutes; loss on a miss is the full stake."

    @classmethod
    def default_params(cls):
        return {"lo": D("0.90"), "hi": D("0.97"), "contracts": 5}

    def decisions(self, m):
        if not self.accepts(m):
            return []
        exp = self._expiry(m)
        out = []
        t = exp - self.window_s
        c = last_candle_before(m.get("candles", []), t)
        if c:
            for side in ("yes", "no"):
                p = ask_for(c, side)
                if p is not None and self.params["lo"] <= p <= self.params["hi"]:
                    out.append(Decision(ts=t, side=side, price=p, count=int(self.params["contracts"])))
                    break
        return out
