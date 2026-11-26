"""Rebuild the backtest cache from Kalshi's public API (settled markets + hourly candles).

Spec v4 §8.6 gap 2: the old summary was generated from "0 Kalshi market histories" -- this
fetcher must be run on Carson's Mac (the cloud build box cannot reach Kalshi).

    python -m kil_capital.backtest.fetch --series KXMLBGAME,KXNBAGAME,KXBTCD,KXHIGHNY --days 365

MSU markets are dropped here AND again at load time (§2.4).
Markets older than GET /historical/cutoff live under /historical/* (§10).
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from ..config import SETTINGS
from ..core import blocklist
from ..venue.public import PublicClient, _ts

log = logging.getLogger("kil.fetch")

DEFAULT_SERIES = ["KXMLBGAME", "KXNBAGAME", "KXNFLGAME", "KXNHLGAME", "KXNCAAFGAME", "KXNCAAMBGAME",
                  "KXBTCD", "KXETHD", "KXBTC", "KXHIGHNY", "KXHIGHCHI", "KXHIGHMIA", "KXCPI", "KXFEDDECISION"]


def _settled_markets(pc: PublicClient, series: str, since_ts: float, historical: bool):
    path = "/historical/markets" if historical else "/markets"
    cursor = None
    while True:
        p = {"series_ticker": series, "limit": 1000}
        if not historical:
            p["status"] = "settled"
        if cursor:
            p["cursor"] = cursor
        try:
            data = pc.get(path, p, ttl=0)
        except Exception as e:
            log.warning("%s %s failed: %s", path, series, e)
            return
        ms = data.get("markets", [])
        for m in ms:
            ct = _ts(m.get("close_time"))
            if ct and ct >= since_ts:
                yield m
        cursor = data.get("cursor")
        if not cursor or not ms:
            return


def fetch(series_list, days: int, cache_dir: Path, period_minutes: int = 60, max_markets: int = 5000,
          pc: PublicClient | None = None) -> int:
    pc = pc or PublicClient(SETTINGS.kalshi_base_url, SETTINGS.public_req_per_sec)
    cache_dir.mkdir(parents=True, exist_ok=True)
    since = time.time() - days * 86400
    n = 0
    for s in series_list:
        try:
            series = pc.series(s)
        except Exception as e:
            log.warning("series %s: %s", s, e)
            series = {"ticker": s}
        seen = set()
        for historical in (False, True):
            for m in _settled_markets(pc, s, since, historical):
                t = m["ticker"]
                if t in seen or n >= max_markets:
                    continue
                seen.add(t)
                if blocklist.check_market(m).blocked:
                    continue
                out = cache_dir / f"{t}.json"
                if out.exists():
                    n += 1
                    continue
                ct = int(_ts(m.get("close_time")) or time.time())
                ot = int(_ts(m.get("open_time")) or ct - 7 * 86400)
                start = max(ot, ct - 14 * 86400)
                try:
                    candles = pc.candles(s, t, start, ct, period_minutes)
                except Exception as e:
                    log.info("candles %s: %s", t, e)
                    candles = []
                out.write_text(json.dumps({"market": m, "series": series, "candles": candles}))
                n += 1
        log.info("series %s: %d markets cached so far", s, n)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default=",".join(DEFAULT_SERIES))
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--period", type=int, default=60, help="candle minutes: 1, 60 or 1440")
    ap.add_argument("--max-markets", type=int, default=5000)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    n = fetch([s.strip() for s in a.series.split(",") if s.strip()], a.days,
              SETTINGS.data_dir / "cache", a.period, a.max_markets)
    print(f"cached {n} markets in {SETTINGS.data_dir / 'cache'}")


if __name__ == "__main__":
    main()
