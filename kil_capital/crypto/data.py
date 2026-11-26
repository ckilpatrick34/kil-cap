"""Coinbase Exchange public candles (free, keyless).  Closed bars are cached on disk."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx

BASE = "https://api.exchange.coinbase.com"


class Candles:
    def __init__(self, cache_dir: Path, client: httpx.Client | None = None):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.http = client or httpx.Client(timeout=20, headers={"User-Agent": "kil-capital-terminal"})
        self._lock = threading.Lock()
        self._mem: dict = {}
        self.last_error: str | None = None

    def _page(self, product: str, gran: int, start: int, end: int) -> list:
        from datetime import datetime, timezone
        iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
        r = self.http.get(f"{BASE}/products/{product}/candles",
                          params={"granularity": gran, "start": iso(start), "end": iso(end)})
        r.raise_for_status()
        time.sleep(0.12)  # stay well under the public rate limit
        return r.json()

    def get(self, product: str, gran: int, days: int, ttl: float = 60) -> list[dict]:
        """Oldest-first bars [{t,o,h,l,c,v}] covering the last `days` days."""
        key = (product, gran, days)
        hit = self._mem.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        f = self.dir / f"{product}-{gran}.json"
        with self._lock:
            try:
                bars = {b["t"]: b for b in json.loads(f.read_text())}
            except (OSError, ValueError):
                bars = {}
            now = int(time.time())
            start = now - days * 86400
            have_to = max([t for t in bars if t < now - gran] or [start])
            cursor = max(start, have_to - gran)
            try:
                while cursor < now:
                    end = min(now, cursor + gran * 299)
                    for t, l, h, o, c, v in self._page(product, gran, cursor, end):
                        bars[t] = {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}
                    cursor = end
            except Exception as e:
                self.last_error = f"{product} {gran}s: {e}"
            out = sorted((b for b in bars.values() if b["t"] >= start), key=lambda b: b["t"])
            closed = [b for b in out if b["t"] + gran <= now]
            try:
                f.write_text(json.dumps(closed))
            except OSError:
                pass
        self._mem[key] = (time.time(), out)
        return out

    def spot(self, product: str) -> float | None:
        try:
            r = self.http.get(f"{BASE}/products/{product}/ticker")
            r.raise_for_status()
            return float(r.json()["price"])
        except Exception as e:
            self.last_error = f"{product} ticker: {e}"
            return None
