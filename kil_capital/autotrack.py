"""Autotracker: a PAPER account that takes every slate pick automatically, so the record is real.

No Kalshi account, no keys, no orders: each pick is written to data/autotrack.json the first time it
appears in the slate, at the ask shown plus Kalshi's taker fee, sized by the same budget rules on its own
$100 paper bankroll.  It is graded when Kalshi settles the market.  Closing-line value is the last
pre-start mid we saw minus the price paid."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from .budget import allocate
from .venue.public import _ts


def fee(count: int, price: float) -> float:
    """Kalshi taker fee: 7% x contracts x P x (1-P), rounded up to the cent."""
    return math.ceil(round(0.07 * count * price * (1 - price) * 100, 6)) / 100


def band(price: float) -> str:
    return "15-35c" if price < 0.35 else "35-50c" if price < 0.5 else "50-65c" if price < 0.65 else "65c+"


class AutoTrack:
    def __init__(self, path: Path, bankroll: float = 100.0, budget: float = 25.0, max_bet: float = 3.0):
        self.path, self.bankroll, self.budget, self.max_bet = Path(path), bankroll, budget, max_bet
        try:
            self.d = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.d = {}
        self.d.setdefault("since", time.time())
        self.d.setdefault("bets", {})

    def save(self):
        self.path.write_text(json.dumps(self.d))

    @property
    def bets(self) -> list[dict]:
        return list(self.d["bets"].values())

    def open_risk(self) -> float:
        return sum(b["cost"] for b in self.bets if b["result"] is None)

    def cash(self) -> float:
        return self.bankroll + sum(b["pnl"] for b in self.bets if b["result"] is not None) - self.open_risk()

    def enter(self, picks: list[dict], version: str, now: float | None = None) -> int:
        """Paper-buy every new slate pick (one entry per ticker, ever) within this account's own budget."""
        now = now or time.time()
        new = [p for p in picks if p.get("slate") and p["ticker"] not in self.d["bets"]]
        room = min(self.budget - self.open_risk(), self.cash())
        n = 0
        for p in allocate(new, self.bankroll, room, self.max_bet):
            if not p["slate"]:
                continue
            f = fee(p["count"], p["price"])
            self.d["bets"][p["ticker"]] = {
                "ts": now, "ticker": p["ticker"], "side": p["side"], "price": p["price"], "count": p["count"],
                "fee": f, "cost": round(p["count"] * p["price"] + f, 2), "fair": p["fair"], "edge": p["edge"],
                "desk": p.get("desk"), "league": p.get("league") or ("Crypto" if p.get("desk") == "crypto" else "?"),
                "kind": p.get("kind"), "grade": p.get("confidence"), "title": p.get("title", ""),
                "start": p.get("start"), "close": p.get("close"), "version": version,
                "last_mid": p.get("mid"), "result": None, "pnl": 0.0, "clv": None}
            n += 1
        return n

    def mark(self, mids: dict, now: float | None = None):
        """Remember the latest YES mid for open bets until their game starts / market closes (for CLV)."""
        now = now or time.time()
        for b in self.bets:
            t = _ts(b.get("start") or b.get("close"))
            if b["result"] is None and b["ticker"] in mids and (t is None or t > now):
                m = mids[b["ticker"]]
                b["last_mid"] = m if b["side"] == "yes" else 1 - m

    def grade(self, public, max_calls: int = 30, now: float | None = None) -> int:
        now, calls, n = now or time.time(), 0, 0
        for b in self.bets:
            t = _ts(b.get("start") or b.get("close"))
            if b["result"] is not None or (t and t > now) or calls >= max_calls:
                continue
            calls += 1
            try:
                res = (public.market(b["ticker"]).get("result") or "").lower()
            except Exception:
                continue
            if res in ("yes", "no"):
                won = res == b["side"]
                b["result"] = "W" if won else "L"
                b["pnl"] = round((b["count"] if won else 0) - b["cost"], 2)
                b["settled"] = now
                if b.get("last_mid") is not None:
                    b["clv"] = round(b["last_mid"] - b["price"], 3)
                n += 1
        return n

    def summary(self, now: float | None = None) -> dict:
        now = now or time.time()
        done = sorted((b for b in self.bets if b["result"] is not None), key=lambda b: b.get("settled", b["ts"]))
        eq, curve = self.bankroll, [[self.d["since"], self.bankroll]]
        for b in done:
            eq += b["pnl"]
            curve.append([b.get("settled", b["ts"]), round(eq, 2)])

        def agg(rows):
            st = sum(r["cost"] for r in rows)
            pnl = sum(r["pnl"] for r in rows)
            w = sum(r["result"] == "W" for r in rows)
            clv = [r["clv"] for r in rows if r.get("clv") is not None]
            return {"n": len(rows), "w": w, "l": len(rows) - w, "win_rate": round(w / len(rows), 3) if rows else None,
                    "staked": round(st, 2), "pnl": round(pnl, 2), "roi": round(pnl / st, 3) if st else None,
                    "avg_clv": round(sum(clv) / len(clv), 3) if clv else None}

        def by(fn):
            g: dict = {}
            for r in done:
                g.setdefault(fn(r), []).append(r)
            return [{"key": k, **agg(v)} for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))]

        opn = sorted((b for b in self.bets if b["result"] is None), key=lambda b: b.get("start") or b.get("close") or "")
        return {"since": self.d["since"], "bankroll": self.bankroll, "budget": self.budget, "max_bet": self.max_bet,
                "equity": round(eq, 2), "open_risk": round(self.open_risk(), 2), "total": agg(done),
                "versions": sorted({b["version"] for b in self.bets}), "curve": curve,
                "open": [{k: b.get(k) for k in ("ticker", "title", "side", "price", "count", "cost", "fair",
                                                "league", "start", "close", "ts")} for b in opn],
                "recent": [{k: b.get(k) for k in ("ticker", "title", "side", "price", "cost", "result", "pnl",
                                                  "clv", "league")} for b in done[-30:][::-1]],
                "by": {"league": by(lambda r: r["league"]), "market": by(lambda r: r.get("kind") or "?"),
                       "side": by(lambda r: "favourite" if r["price"] >= 0.5 else "underdog"),
                       "price": by(lambda r: band(r["price"])), "grade": by(lambda r: r.get("grade") or "?")}}
