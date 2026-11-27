"""Forward recorders: real Kalshi data, recorded with NO orders, to test the maker leads before anything is built.

Each publish run (~every 2.5 min) appends to data/recorders/<UTC day>/<stream>.jsonl.gz:
  quotes    top of book for every market closing within 24h that is a tail (one side <= 15c) or an hourly
            BTC/ETH market; a row is written only when bid/ask changed.  Prices in cents.
  tape      every exchange trade in those markets (price, size, taker side).  Who got filled is in here:
            a resting maker on the other side of `s` (taker side) at that price.
  books     depth-5 order book the first time a market is recorded (queue ahead of a hypothetical quote).
  settle    final result of each recorded market.
  fees      each series' fee type / multiplier as Kalshi reports it (maker fees are per series).
  incentives raw liquidity-reward program list, hourly (endpoint unverified: failure is recorded, not hidden).
Pass/fail rules are fixed in RECORDERS.md before the data exists.  Analysis reads these files; nothing here
decides or trades."""
from __future__ import annotations

import gzip
import json
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..venue.public import _dollars, _ts

CRYPTO = ("KXBTC", "KXETH")      # hourly/daily BTC and ETH ladders (spike-fade lead)
TAIL = 15                        # cents: longshot <= 15c on either side (covers <=10c sells and >=85c favourites)
HORIZON = 24 * 3600
KEEP_DAYS = 35
MAX_PAGES = 12                   # x1000 markets / trades per run
MAX_BOOKS = 20
MAX_BYTES = 400e6                # stop writing (and say so) rather than bloat the state branch


def _c(x):
    return None if x is None else int(round(float(x) * 100))


class Recorder:
    def __init__(self, public, data_dir: Path):
        self.pub, self.dir = public, Path(data_dir) / "recorders"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sp = self.dir / "state.json"
        self.st = json.loads(self.sp.read_text()) if self.sp.exists() else {}
        for k, v in (("quotes", {}), ("track", {}), ("booked", []), ("series", {}), ("days", {})):
            self.st.setdefault(k, v)

    def _w(self, stream: str, rows: list, now: float):
        if not rows:
            return
        day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
        d = self.dir / day
        d.mkdir(exist_ok=True)
        with gzip.open(d / f"{stream}.jsonl.gz", "at") as f:   # appended gzip members read back as one stream
            f.writelines(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)
        cnt = self.st["days"].setdefault(day, {})
        cnt[stream] = cnt.get(stream, 0) + len(rows)

    def _pages(self, path, params):
        cursor, n = None, 0
        while n < MAX_PAGES:
            d = self.pub.get(path, {**params, **({"cursor": cursor} if cursor else {})}, ttl=0)
            yield d
            cursor, n = d.get("cursor"), n + 1
            if not cursor:
                return
        self.errors.append(f"{path}: page cap hit, data truncated this run")

    def run(self, now: float | None = None, budget_s: float = 60) -> dict:
        now, t0, self.errors = now or time.time(), time.time(), []
        if sum(f.stat().st_size for f in self.dir.rglob("*") if f.is_file()) > MAX_BYTES:
            self.errors.append("recorder size cap hit: not writing")
            return self.status(now)
        steps = (self._sweep, self._tape, self._settle, self._fees, self._incentives)
        for step in steps:
            if time.time() - t0 > budget_s:
                self.errors.append(f"time budget hit before {step.__name__}")
                break
            try:
                step(now)
            except Exception as e:  # one failing stream must not stop the others
                self.errors.append(f"{step.__name__}: {e}")
        self._prune(now)
        self.st["last_run"], self.st["last_errors"] = now, self.errors
        self.sp.write_text(json.dumps(self.st, separators=(",", ":")))
        return self.status(now)

    def _sweep(self, now):
        q, track, booked = self.st["quotes"], self.st["track"], set(self.st["booked"])
        rows, books = [], []
        params = {"status": "open", "limit": 1000, "min_close_ts": int(now), "max_close_ts": int(now + HORIZON)}
        for d in self._pages("/markets", params):
            for m in d.get("markets", []):
                t = m.get("ticker", "")
                if t.startswith("KXMVE"):        # multi-leg combos: not part of any lead
                    continue
                b, a = _c(_dollars(m, "yes_bid")), _c(_dollars(m, "yes_ask"))
                tail = (a is not None and 0 < a <= TAIL) or (b is not None and b >= 100 - TAIL)
                if not (tail or t.startswith(CRYPTO)):
                    continue
                track[t] = _ts(m.get("close_time")) or now + HORIZON
                if q.get(t) != [b, a]:
                    q[t] = [b, a]
                    rows.append({"ts": int(now), "t": t, "b": b, "a": a, "last": _c(_dollars(m, "last_price")),
                                 "v": m.get("volume"), "oi": m.get("open_interest"), "c": int(track[t])})
                if tail and t not in booked and len(books) < MAX_BOOKS:
                    ob = self.pub.orderbook(t, depth=5)
                    books.append({"ts": int(now), "t": t, "ob": ob})
                    booked.add(t)
        self._w("quotes", rows, now)
        self._w("books", books, now)
        self.st["booked"] = sorted(booked & set(track))

    def _tape(self, now):
        track, seen = self.st["track"], set(self.st.get("tape_ids", []))
        since = self.st.get("tape_ts") or now - 300
        rows, newest, ids = [], since, []
        for d in self._pages("/markets/trades", {"limit": 1000, "min_ts": int(since) - 5}):
            for tr in d.get("trades", []):
                t, tid = tr.get("ticker", ""), tr.get("trade_id")
                ts = _ts(tr.get("created_time")) or now
                newest = max(newest, ts)
                ids.append(tid)
                if tid in seen or not (t in track or t.startswith(CRYPTO)):
                    continue
                rows.append({"ts": round(ts, 3), "t": t, "p": _c(_dollars(tr, "yes_price")),
                             "n": tr.get("count") if tr.get("count") is not None else tr.get("count_fp"),
                             "s": tr.get("taker_side"), "id": tid})
        self._w("tape", rows, now)
        self.st["tape_ts"], self.st["tape_ids"] = newest, ids[:3000]

    def _settle(self, now):
        track = self.st["track"]
        due = [t for t, c in track.items() if c < now - 300][:400]
        rows = []
        for i in range(0, len(due), 100):
            d = self.pub.get("/markets", {"tickers": ",".join(due[i:i + 100]), "limit": 100}, ttl=0)
            for m in d.get("markets", []):
                t = m.get("ticker")
                if t not in track:
                    continue
                if m.get("result") in ("yes", "no") or m.get("status") in ("settled", "finalized"):
                    rows.append({"ts": int(now), "t": t, "result": m.get("result"), "status": m.get("status"),
                                 "settle": m.get("settlement_value"), "c": int(track.get(t, now))})
                    track.pop(t, None)
                    self.st["quotes"].pop(t, None)
        for t in [t for t, c in track.items() if c < now - 3 * 86400]:   # never settled: stop asking, say so
            rows.append({"ts": int(now), "t": t, "result": None, "status": "unsettled_after_3d"})
            track.pop(t)
            self.st["quotes"].pop(t, None)
        self._w("settle", rows, now)

    def _fees(self, now):
        have, rows = self.st["series"], []
        for s in sorted({t.split("-")[0] for t in self.st["track"]} - set(have))[:15]:
            x = self.pub.series(s)
            have[s] = {k: x.get(k) for k in ("fee_type", "fee_multiplier", "category")}
            rows.append({"ts": int(now), "series": s, **{k: x.get(k) for k in x if "fee" in k}})
        self._w("fees", rows, now)

    def _incentives(self, now):
        if now - self.st.get("inc_ts", 0) < 3600:
            return
        self.st["inc_ts"] = now
        try:
            d = self.pub.get("/incentive_programs", {"limit": 1000}, ttl=0)
            self.st["inc_status"] = "ok"
            self._w("incentives", [{"ts": int(now), "raw": d}], now)
        except Exception as e:
            self.st["inc_status"] = f"unavailable: {str(e)[:120]}"

    def _prune(self, now):
        cut = (datetime.fromtimestamp(now, timezone.utc) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
        for d in self.dir.iterdir():
            if d.is_dir() and d.name < cut:
                shutil.rmtree(d)
                self.st["days"].pop(d.name, None)

    def status(self, now: float | None = None) -> dict:
        days = self.st["days"]
        return {"mode": "RECORD-ONLY, no orders", "days": len(days), "first_day": min(days) if days else None,
                "today": days.get(datetime.fromtimestamp(now or time.time(), timezone.utc).strftime("%Y-%m-%d"), {}),
                "totals": {k: sum(v.get(k, 0) for v in days.values())
                           for k in ("quotes", "tape", "books", "settle", "fees", "incentives")},
                "tracking": len(self.st["track"]), "incentives": self.st.get("inc_status"),
                "last_run": self.st.get("last_run"), "errors": self.st.get("last_errors", [])}
