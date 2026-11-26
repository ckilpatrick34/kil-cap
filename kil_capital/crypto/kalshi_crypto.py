"""Price Kalshi's BTC/ETH price contracts from a volatility model.

Fair P(settle above K) treats log-price at expiry as zero-drift with hourly EWMA volatility, using a two-part
normal mixture (most hours calm, some wild) so the tails are fatter than a plain bell curve - crypto's are.
Signals use the same gates as the sports desk: edge after the taker fee, no longshots, and enough time left."""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from ..venue.public import _dollars

SERIES = {"BTC-USD": ("KXBTCD", "KXBTC"), "ETH-USD": ("KXETHD", "KXETH")}
MIX = ((0.8, 0.85), (0.2, 1.40))          # (weight, sigma multiplier); variance ~= 0.97 of the base
LONGSHOT = 0.15
STRATEGY_ID = "crypto_vol"


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def p_above(spot: float, k: float, hours: float, sigma_h: float) -> float:
    if hours <= 0:
        return 1.0 if spot > k else 0.0
    z = math.log(k / spot)
    return sum(w * (1 - _ncdf(z / (sigma_h * m * math.sqrt(hours)))) for w, m in MIX)


def p_contract(m: dict, spot: float, hours: float, sigma_h: float) -> float | None:
    st = (m.get("strike_type") or "").lower()
    lo, hi = m.get("floor_strike"), m.get("cap_strike")
    if st in ("greater", "greater_or_equal") and lo is not None:
        return p_above(spot, float(lo), hours, sigma_h)
    if st in ("less", "less_or_equal") and hi is not None:
        return 1 - p_above(spot, float(hi), hours, sigma_h)
    if st == "between" and lo is not None and hi is not None:
        return p_above(spot, float(lo), hours, sigma_h) - p_above(spot, float(hi), hours, sigma_h)
    return None


def _ts(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def price_markets(markets: list[dict], spot: float, sigma_h: float, min_edge: float = 0.03,
                  now: float | None = None, equity: float = 1000.0, max_trade: float = 50.0) -> list[dict]:
    now = now or time.time()
    rows = []
    for m in markets:
        exp = _ts(m.get("expected_expiration_time") or m.get("close_time"))
        if not exp:
            continue
        hours = (exp - now) / 3600
        q = p_contract(m, spot, hours, sigma_h)
        if q is None:
            continue
        yb, ya = _dollars(m, "yes_bid"), _dollars(m, "yes_ask")
        yb, ya = (float(yb) if yb else None), (float(ya) if ya else None)
        best = None
        for side, price, fair in (("yes", ya, q), ("no", round(1 - yb, 2) if yb else None, 1 - q)):
            if not price or not (0 < price < 1):
                continue
            edge = fair - price - 0.07 * price * (1 - price)
            if best is None or edge > best["edge"]:
                best = {"side": side, "price": price, "fair": fair, "edge": edge}
        row = {"ticker": m["ticker"], "title": m.get("title", ""), "sub": m.get("yes_sub_title") or "",
               "strike_type": m.get("strike_type"), "floor": m.get("floor_strike"), "cap": m.get("cap_strike"),
               "hours": round(hours, 2), "close": datetime.fromtimestamp(exp, timezone.utc).isoformat(), "yes_bid": yb, "yes_ask": ya, "fair_yes": round(q, 4), "best": best,
               "tradeable": False}
        if best:
            kelly = max(0.0, 0.25 * (best["fair"] - best["price"]) / (1 - best["price"]))
            stake = min(max_trade, kelly * equity)
            row["count"] = int(stake / (best["price"] + 0.02))
            row["stake"] = round(stake, 2)
            row["tradeable"] = (best["edge"] >= min_edge and LONGSHOT <= best["price"] <= 0.92
                                and hours >= 0.25 and row["count"] >= 1)
        rows.append(row)
    return rows


def fetch(public, series: str, max_pages: int = 3) -> list[dict]:
    out, cursor = [], None
    for _ in range(max_pages):
        try:
            ms, cursor = public.markets(status="open", series_ticker=series, limit=1000, cursor=cursor)
        except Exception:
            break
        out += ms
        if not cursor:
            break
    return out
