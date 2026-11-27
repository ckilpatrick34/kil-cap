"""Forward track record for every game_model signal: logged the first time it appears (pre-game, at the
price we'd have paid), graded when Kalshi settles it.  Results are bucketed by league x market x edge size,
and each bucket's calibration gap (how much our fair overstated the real hit rate) shrinks future fair
prices once the bucket has real data - the honest version of what Big Vin does, with no hindsight tuning."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from ..venue.public import _ts

PRIOR = 100          # a bucket needs this many graded picks to get half weight on its own record


def edge_bucket(edge: float) -> str:
    return "3-5c" if edge < 0.05 else "5-10c" if edge < 0.10 else "10c+"


class Track:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        try:
            self.rows = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.rows = {}

    def _save(self):
        try:
            self.path.write_text(json.dumps(self.rows))
        except OSError:
            pass

    def record(self, sig: dict, league: str, kind: str, close_ts: float | None):
        k = f"{sig['ticker']}:{sig['side']}"
        with self._lock:
            if k in self.rows:
                return
            self.rows[k] = {"ticker": sig["ticker"], "side": sig["side"], "price": sig["price"],
                            "fair": sig["fair"], "edge": sig["edge"], "league": league, "kind": kind,
                            "bucket": edge_bucket(sig["edge"]), "title": sig.get("title", ""),
                            "close_ts": close_ts, "start": sig.get("start"), "logged": time.time(), "result": None,
                            "model_fair": sig.get("model_fair"), "mid": sig.get("mid")}
            self._save()

    def grade(self, public, clv_for=None, max_calls: int = 60, now: float | None = None):
        """Settle pending picks whose game should be over.  Kalshi's close_time on game markets is a backstop
        days after the game (it settles hours after the final), so gate on game start, not close_time.
        Least-recently-checked first, at most once per 30 min each, bounded so it never stalls a refresh."""
        now, calls, changed = now or time.time(), 0, False
        due = []
        for r in self.rows.values():
            if r["result"] is not None or now - r.get("checked", 0) < 1800:
                continue
            close = _ts(r["close_ts"]) if isinstance(r.get("close_ts"), str) else r.get("close_ts")
            start = _ts(r["start"]) if r.get("start") else None
            over = (start or r["logged"]) + 3 * 3600 <= now   # no start: assume the game was near logging
            if not over and not (close is not None and close <= now):
                continue
            due.append(r)
        for r in sorted(due, key=lambda r: r.get("checked", 0))[:max_calls]:
            calls += 1
            r["checked"], changed = now, True
            try:
                m = public.market(r["ticker"])
            except Exception:
                continue
            res = (m.get("result") or "").lower()
            if res in ("yes", "no"):
                r["result"] = "W" if res == r["side"] else "L"
                r["pnl"] = round((1 - r["price"] if r["result"] == "W" else -r["price"])
                                 - 0.07 * r["price"] * (1 - r["price"]), 4)
                if clv_for:
                    r["clv"] = clv_for(r["ticker"], r["side"], r["price"])
                changed = True
        if changed:
            with self._lock:
                self._save()

    def buckets(self) -> dict:
        out: dict = {}
        for r in self.rows.values():
            if r["result"] is None:
                continue
            b = out.setdefault((r["league"], r["kind"], r["bucket"]),
                               {"n": 0, "w": 0, "fair": 0.0, "price": 0.0, "pnl": 0.0, "clv": [], "staked": 0.0})
            b["n"] += 1
            b["w"] += r["result"] == "W"
            b["fair"] += r["fair"]
            b["price"] += r["price"]
            b["pnl"] += r["pnl"]
            b["staked"] += r["price"]
            if r.get("clv") is not None:
                b["clv"].append(r["clv"])
        return out

    def shrink(self, league: str, kind: str, edge: float, fair: float) -> float:
        """Pull a fair price toward what this bucket has actually hit (0 effect until data exists)."""
        b = self.buckets().get((league, kind, edge_bucket(edge)))
        if not b or b["n"] < 10:
            return fair
        gap = b["fair"] / b["n"] - b["w"] / b["n"]          # >0 means we've been overconfident here
        return fair - gap * b["n"] / (b["n"] + PRIOR)

    def summary(self) -> dict:
        rows = []
        for (lg, kind, bk), b in sorted(self.buckets().items()):
            rows.append({"league": lg, "kind": kind, "bucket": bk, "n": b["n"], "wins": b["w"],
                         "hit": round(b["w"] / b["n"], 3), "avg_fair": round(b["fair"] / b["n"], 3),
                         "avg_price": round(b["price"] / b["n"], 3),
                         "roi": round(b["pnl"] / b["staked"], 3) if b["staked"] else None,
                         "clv": round(sum(b["clv"]) / len(b["clv"]), 3) if b["clv"] else None})
        pending = sum(r["result"] is None for r in self.rows.values())
        graded = [r for r in self.rows.values() if r["result"] is not None]
        tot = {"graded": len(graded), "pending": pending,
               "wins": sum(r["result"] == "W" for r in graded),
               "pnl_per_contract": round(sum(r["pnl"] for r in graded), 3)}
        return {"total": tot, "buckets": rows}
