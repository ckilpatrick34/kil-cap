"""Backtest data model: normalise cached Kalshi markets + candles into point-in-time dicts.

Market dict:
    ticker, event_ticker, series_ticker, category, title, yes_sub_title, opponent,
    result ('yes'|'no'), open_ts, close_ts, expected_expiration_ts, fee_type, fee_multiplier,
    price_ranges (raw), candles=[{ts, yes_bid, yes_ask, price, price_low, price_high, volume}]
Candle ts is the END of the period (data is only known after it), so a decision at time t may use
candles with ts <= t.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Optional

from ..core import blocklist
from ..venue.public import _ts

D = Decimal


def _px(obj, key="close") -> Optional[Decimal]:
    if not isinstance(obj, dict):
        return None
    v = obj.get(f"{key}_dollars")
    if v not in (None, ""):
        return D(str(v))
    v = obj.get(key)
    if v in (None, ""):
        return None
    return D(str(v)) / 100


def _int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def normalise_candles(raw: list) -> list[dict]:
    out = []
    for c in raw or []:
        ts = c.get("end_period_ts") or c.get("ts")
        if ts is None:
            continue
        price = c.get("price") or {}
        out.append({
            "ts": float(ts),
            "yes_bid": _px(c.get("yes_bid"), "close"),
            "yes_ask": _px(c.get("yes_ask"), "close"),
            "price": _px(price, "close"),
            "price_low": _px(price, "low"),
            "price_high": _px(price, "high"),
            "volume": _int(c.get("volume", c.get("volume_fp"))),
        })
    out.sort(key=lambda x: x["ts"])
    return out


def normalise_market(m: dict, candles_raw: list, series: Optional[dict] = None) -> Optional[dict]:
    series = series or {}
    res = (m.get("result") or "").lower()
    if res not in ("yes", "no"):
        return None
    close_ts = _ts(m.get("close_time"))
    if close_ts is None:
        return None
    return {
        "ticker": m["ticker"],
        "event_ticker": m.get("event_ticker"),
        "series_ticker": m.get("series_ticker") or series.get("ticker"),
        "category": m.get("category") or series.get("category"),
        "title": m.get("title", ""),
        "yes_sub_title": m.get("yes_sub_title"),
        "no_sub_title": m.get("no_sub_title"),
        "rules_primary": m.get("rules_primary", ""),
        "result": res,
        "open_ts": _ts(m.get("open_time")),
        "close_ts": close_ts,
        "expected_expiration_ts": _ts(m.get("expected_expiration_time")),
        "fee_type": series.get("fee_type") or "quadratic",
        "fee_multiplier": str(series.get("fee_multiplier", 1)),
        "price_ranges": m.get("price_ranges"),
        "mutually_exclusive": m.get("mutually_exclusive"),
        "candles": normalise_candles(candles_raw),
    }


def attach_opponents(markets: list[dict]) -> None:
    by_ev = defaultdict(list)
    for m in markets:
        by_ev[m.get("event_ticker")].append(m)
    for ms in by_ev.values():
        if len(ms) == 2:
            a, b = ms
            a["opponent"], b["opponent"] = b.get("yes_sub_title"), a.get("yes_sub_title")


def load_cache(cache_dir: Path) -> list[dict]:
    """Load every cached market file, dropping blocked (MSU) markets so they cannot influence research."""
    out = []
    for f in sorted(Path(cache_dir).glob("*.json")):
        try:
            blob = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        m = normalise_market(blob.get("market", {}), blob.get("candles", []), blob.get("series"))
        if m and not blocklist.check_market(m).blocked:
            out.append(m)
    attach_opponents(out)
    out.sort(key=lambda m: m["close_ts"])
    return out


def data_hash(markets: list[dict]) -> str:
    h = hashlib.sha256()
    for m in markets:
        h.update(f"{m['ticker']}|{m['result']}|{m['close_ts']}|{len(m['candles'])}".encode())
    return h.hexdigest()[:16]
