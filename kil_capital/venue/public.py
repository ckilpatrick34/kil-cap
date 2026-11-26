"""Read-only Kalshi public API: paced (~2 req/s), cached, exponential backoff on 429 (§9, §10).

The browser never calls Kalshi directly; the backend proxies through this client.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from decimal import Decimal
from typing import Optional

import httpx

from ..core import blocklist, desks
from ..core.money import parse_price_ranges
from ..core.orders import MarketInfo

log = logging.getLogger("kil.public")
D = Decimal


def _dollars(m: dict, key: str) -> Optional[Decimal]:
    """Kalshi returns either `<key>_dollars` strings or legacy integer cents in `<key>`."""
    v = m.get(f"{key}_dollars")
    if v not in (None, ""):
        return D(str(v))
    v = m.get(key)
    if v in (None, ""):
        return None
    return D(str(v)) / 100


def _ts(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def market_info(m: dict, series: Optional[dict] = None) -> MarketInfo:
    series = series or {}
    strike, direction = None, None
    if m.get("strike_type") in ("greater", "greater_or_equal") and m.get("floor_strike") is not None:
        strike, direction = D(str(m["floor_strike"])), "above"
    elif m.get("strike_type") in ("less", "less_or_equal") and m.get("cap_strike") is not None:
        strike, direction = D(str(m["cap_strike"])), "below"
    return MarketInfo(
        ticker=m.get("ticker", ""),
        status=m.get("status", "unknown"),
        event_ticker=m.get("event_ticker"),
        series_ticker=m.get("series_ticker") or series.get("ticker") or desks.series_of(m.get("event_ticker", "")),
        category=m.get("category") or series.get("category"),
        title=m.get("title", ""),
        price_ranges=parse_price_ranges(m.get("price_ranges")),
        yes_bid=_dollars(m, "yes_bid"),
        yes_ask=_dollars(m, "yes_ask"),
        close_ts=_ts(m.get("close_time")),
        fee_type=series.get("fee_type") or m.get("fee_type") or "quadratic",
        fee_multiplier=D(str(series.get("fee_multiplier", m.get("fee_multiplier", 1)))),
        strike=strike,
        strike_direction=direction,
        raw=m,
    )


class PublicClient:
    def __init__(self, base_url: str, req_per_sec: float = 2.0, client: Optional[httpx.Client] = None,
                 cache_ttl: float = 5.0):
        self.base = base_url.rstrip("/")
        self._min_gap = 1.0 / req_per_sec
        self._last = 0.0
        self._lock = threading.Lock()
        self._cache: dict = {}
        self._ttl = cache_ttl
        self._client = client or httpx.Client(timeout=15.0, headers={"User-Agent": "kil-capital-terminal"})
        self.last_ok: Optional[float] = None
        self.last_error: Optional[str] = None

    def get(self, path: str, params: Optional[dict] = None, ttl: Optional[float] = None, retries: int = 4):
        key = (path, tuple(sorted((params or {}).items())))
        ttl = self._ttl if ttl is None else ttl
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        delay = 1.0
        for attempt in range(retries + 1):
            with self._lock:
                wait = self._min_gap - (time.time() - self._last)
                if wait > 0:
                    time.sleep(wait)
                self._last = time.time()
            try:
                r = self._client.get(self.base + path, params=params)
            except httpx.HTTPError as e:
                self.last_error = str(e)
                if attempt == retries:
                    raise
                time.sleep(delay)
                delay *= 2
                continue
            if r.status_code == 429 and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            if r.status_code >= 400:
                self.last_error = f"{r.status_code} {r.text[:200]}"
                r.raise_for_status()
            data = r.json()
            self._cache[key] = (time.time(), data)
            if len(self._cache) > 5000:
                self._cache.clear()
            self.last_ok = time.time()
            return data
        raise RuntimeError("unreachable")

    # ---- convenience -----------------------------------------------------------------
    def series(self, series_ticker: str) -> dict:
        return self.get(f"/series/{series_ticker}", ttl=3600).get("series", {})

    def series_list(self, category: Optional[str] = None) -> list:
        return self.get("/series", {"category": category} if category else None, ttl=3600).get("series", [])

    def markets(self, *, status="open", series_ticker=None, event_ticker=None, limit=200, cursor=None,
                include_blocked=False) -> tuple[list, Optional[str]]:
        p = {"limit": limit}
        if status:
            p["status"] = status
        if series_ticker:
            p["series_ticker"] = series_ticker
        if event_ticker:
            p["event_ticker"] = event_ticker
        if cursor:
            p["cursor"] = cursor
        data = self.get("/markets", p, ttl=10)
        ms = data.get("markets", [])
        if not include_blocked:
            ms = blocklist.filter_markets(ms)   # MSU markets are hidden (§2.4)
        return ms, data.get("cursor") or None

    def market(self, ticker: str) -> dict:
        return self.get(f"/markets/{ticker}", ttl=3).get("market", {})

    def market_info(self, ticker: str) -> MarketInfo:
        m = self.market(ticker)
        st = m.get("series_ticker") or desks.series_of(ticker)
        try:
            s = self.series(st)
        except Exception:  # series lookup failing must not hide the market
            s = {}
        return market_info(m, s)

    def orderbook(self, ticker: str, depth: int = 20) -> dict:
        return self.get(f"/markets/{ticker}/orderbook", {"depth": depth}, ttl=1).get("orderbook", {})

    def trades(self, ticker: str, limit: int = 100, min_ts=None, max_ts=None, cursor=None) -> dict:
        p = {"ticker": ticker, "limit": limit}
        if min_ts:
            p["min_ts"] = int(min_ts)
        if max_ts:
            p["max_ts"] = int(max_ts)
        if cursor:
            p["cursor"] = cursor
        return self.get("/markets/trades", p, ttl=2)

    def candles(self, series_ticker: str, ticker: str, start_ts: int, end_ts: int, period_minutes: int = 60) -> list:
        p = {"start_ts": int(start_ts), "end_ts": int(end_ts), "period_interval": period_minutes}
        data = self.get(f"/series/{series_ticker}/markets/{ticker}/candlesticks", p, ttl=30)
        return data.get("candlesticks", [])

    def event(self, event_ticker: str) -> dict:
        return self.get(f"/events/{event_ticker}", ttl=30)

    def historical_cutoff(self) -> dict:
        return self.get("/historical/cutoff", ttl=3600)
