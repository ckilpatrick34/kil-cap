"""Crypto desk service: daily strategy backtests (cached), live strategy positions, Kalshi crypto signals,
and paper P&L for every strategy since the day it went live here (forward-tested, never re-fit)."""
from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import indicators as I
from .backtest import FEE_PER_SIDE, evaluate, metrics, run
from .data import Candles
from .kalshi_crypto import SERIES, STRATEGY_ID, fetch, price_markets
from .strategies import STRATEGIES

PRODUCTS = ("BTC-USD", "ETH-USD")


class CryptoDesk:
    def __init__(self, public, data_dir: Path, candles: Candles | None = None):
        self.public = public
        self.dir = Path(data_dir)
        self.candles = candles or Candles(self.dir / "candles")
        self._bt: dict = {}
        self._lock = threading.Lock()
        self.live_path = self.dir / "crypto_live.json"
        try:
            self.live_since = json.loads(self.live_path.read_text())
        except (OSError, ValueError):
            self.live_since = {}
        self.state = {"updated": None, "products": {}, "signals": [], "errors": []}

    def _backtest(self, product: str, daily: list[dict]) -> dict:
        hit = self._bt.get(product)
        if hit and time.time() - hit[0] < 6 * 3600:
            return hit[1]
        closes = [b["c"] for b in daily]
        res = evaluate(closes) if len(closes) > 400 else {}
        self._bt[product] = (time.time(), res)
        return res

    def _forward(self, product: str, daily: list[dict]) -> dict:
        """Paper P&L of each strategy since it went live here: same rules, no refitting."""
        if not daily:
            return {}
        today = daily[-1]["t"]
        changed = False
        out = {}
        closes = [b["c"] for b in daily]
        for key, (_n, _d, fn) in STRATEGIES.items():
            k = f"{product}:{key}"
            if k not in self.live_since:
                self.live_since[k] = today
                changed = True
            start = next((i for i, b in enumerate(daily) if b["t"] >= self.live_since[k]), len(daily) - 1)
            pos = fn(closes)
            bt = run(closes[start:], pos[start:], FEE_PER_SIDE) if len(closes) - start > 1 else {"rets": []}
            eq = 1.0
            for r in bt["rets"]:
                eq *= 1 + r
            out[key] = {"since": datetime.fromtimestamp(self.live_since[k], timezone.utc).date().isoformat(),
                        "return": round(eq - 1, 4), "days": len(bt["rets"])}
        if changed:
            try:
                self.live_path.write_text(json.dumps(self.live_since))
            except OSError:
                pass
        return out

    def refresh(self, min_edge: float = 0.03, equity: float = 1000.0, max_trade: float = 50.0) -> dict:
        products, signals, errors = {}, [], []
        for prod in PRODUCTS:
            try:
                daily = self.candles.get(prod, 86400, 2000, ttl=1800)
                hourly = self.candles.get(prod, 3600, 60, ttl=120)
                spot = self.candles.spot(prod) or (hourly[-1]["c"] if hourly else None)
                if not daily or not hourly or not spot:
                    errors.append(f"{prod}: no price data ({self.candles.last_error})")
                    continue
                vol_h = I.ewma_vol(I.log_returns([b["c"] for b in hourly]))[-1] or 0.006
                closes = [b["c"] for b in daily]
                rsi14 = I.rsi(closes, 14)[-1]
                bt = self._backtest(prod, daily)
                fwd = self._forward(prod, daily)
                strategies = []
                for key, r in bt.items():
                    strategies.append({"id": key, **{k: v for k, v in r.items()}, "forward": fwd.get(key)})
                kal = []
                for series in SERIES[prod]:
                    kal += price_markets(fetch(self.public, series), spot, vol_h, min_edge,
                                         equity=equity, max_trade=max_trade)
                kal.sort(key=lambda r: (r["hours"], r.get("floor") or 0))
                for r in kal:
                    if r["tradeable"]:
                        b = r["best"]
                        signals.append({"ticker": r["ticker"], "side": b["side"], "price": b["price"],
                                        "edge": round(b["edge"], 4), "fair": round(b["fair"], 4),
                                        "strategy_id": STRATEGY_ID, "count": r["count"], "stake": r["stake"],
                                        "confidence": "B" if r["hours"] <= 24 else "C",
                                        "title": f"{prod.split('-')[0]} {r['sub'] or r['title']} {b['side'].upper()}"})
                products[prod] = {
                    "spot": spot, "vol_hourly": vol_h, "vol_annual": vol_h * math.sqrt(24 * 365), "rsi14": rsi14,
                    "sma50": I.sma(closes, 50)[-1], "sma200": I.sma(closes, 200)[-1],
                    "chart": [[b["t"], b["c"]] for b in daily[-365:]],
                    "strategies": strategies, "kalshi": kal[:80]}
            except Exception as e:
                errors.append(f"{prod}: {e}")
        signals.sort(key=lambda s: -s["edge"])
        with self._lock:
            self.state = {"updated": datetime.now(timezone.utc).isoformat(), "products": products,
                          "signals": signals, "errors": errors}
        return self.state

    def snapshot(self) -> dict:
        with self._lock:
            return self.state
