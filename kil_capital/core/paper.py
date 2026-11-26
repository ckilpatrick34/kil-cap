"""Paper book and autopilot.  Simulated money only.

Nothing in this module can reach Kalshi's trading API: it imports no venue code and never calls the
gateway.  Paper fills are priced conservatively (buy at the ask, sell at the bid, taker fee).
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

from . import blocklist, money

D = Decimal
ZERO = D("0")
ONE = D("1")


@dataclass
class AutopilotSettings:
    enabled: bool = False              # always starts OFF; Carson turns it on
    min_edge: str = "0.03"             # skip signals with edge below 3 cents
    max_trade_usd: str = "10"          # cost of one paper trade
    max_total_usd: str = "200"         # total paper money at risk
    max_positions: int = 15
    min_price: str = "0.03"            # skip near-zero / near-one prices
    max_price: str = "0.97"
    strategies: list = field(default_factory=list)   # empty = every strategy


def _fee(price: Decimal, count: int) -> Decimal:
    try:
        return money.fee(price, count, fee_type="quadratic", multiplier=1, liquidity="taker")
    except ValueError:
        return ZERO


class PaperBook:
    def __init__(self, path: Path, start_cash: Decimal = D("1000")):
        self.path = Path(path)
        self.start_cash = start_cash
        self._lock = threading.RLock()
        self.cash = start_cash
        self.positions: dict[str, dict] = {}
        self.history: list[dict] = []   # every paper fill / settlement, newest last
        self.log: list[dict] = []       # autopilot activity, newest last
        self.auto = AutopilotSettings()
        self._load()
        self.auto.enabled = False       # never resume autopilot silently after a restart

    # ---- persistence ------------------------------------------------------------------
    def _load(self):
        if not self.path.exists():
            return
        try:
            d = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        self.cash = D(d.get("cash", str(self.start_cash)))
        self.positions = d.get("positions", {})
        self.history = d.get("history", [])[-1000:]
        self.log = d.get("log", [])[-300:]
        a = d.get("autopilot") or {}
        self.auto = AutopilotSettings(**{k: v for k, v in a.items() if k in AutopilotSettings.__dataclass_fields__})

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"cash": str(self.cash), "positions": self.positions,
                                   "history": self.history[-1000:], "log": self.log[-300:],
                                   "autopilot": asdict(self.auto)}, indent=1))
        tmp.replace(self.path)

    def note(self, msg: str, **extra):
        with self._lock:
            self.log.append({"ts": time.time(), "msg": msg, **extra})
            self.log = self.log[-300:]
            self._save()

    # ---- trading ----------------------------------------------------------------------------
    def buy(self, *, ticker: str, side: str, price, count: int, strategy_id: str = "manual",
            title: str = "", fair=None, actor: str = "carson") -> dict:
        side = side.lower()
        price = D(str(price))
        if side not in ("yes", "no"):
            raise ValueError("side must be yes or no")
        if not (ZERO < price < ONE):
            raise ValueError("price must be between 1 and 99 cents")
        if count < 1:
            raise ValueError("count must be at least 1")
        if blocklist.is_blocked({"ticker": ticker, "title": title}):
            raise ValueError("Mississippi State markets are blocked")
        with self._lock:
            p = self.positions.get(ticker)
            if p and p["side"] != side:
                raise ValueError(f"already hold {p['side'].upper()} on this market; close it first")
            fee = _fee(price, count)
            cost = price * count + fee
            if cost > self.cash:
                raise ValueError(f"not enough paper cash (${self.cash:.2f})")
            self.cash -= cost
            if p:
                n = p["count"] + count
                p["avg_price"] = str(((D(p["avg_price"]) * p["count"]) + price * count) / n)
                p["count"] = n
                p["fees"] = str(D(p["fees"]) + fee)
            else:
                self.positions[ticker] = {"ticker": ticker, "side": side, "count": count, "avg_price": str(price),
                                          "fees": str(fee), "strategy_id": strategy_id, "title": title,
                                          "fair": None if fair is None else str(fair), "opened": time.time()}
            row = {"ts": time.time(), "kind": "buy", "ticker": ticker, "side": side, "price": str(price),
                   "count": count, "fee": str(fee), "strategy_id": strategy_id, "title": title, "actor": actor}
            self.history.append(row)
            self._save()
            return row

    def close(self, ticker: str, bid, actor: str = "carson") -> dict:
        """Sell the whole position at the current bid for its side."""
        bid = D(str(bid))
        with self._lock:
            p = self.positions.get(ticker)
            if not p:
                raise ValueError("no paper position on that market")
            if not (ZERO < bid < ONE):
                raise ValueError("no bid to sell into right now")
            fee = _fee(bid, p["count"])
            proceeds = bid * p["count"] - fee
            pnl = proceeds - (D(p["avg_price"]) * p["count"] + D(p["fees"]))
            self.cash += proceeds
            del self.positions[ticker]
            row = {"ts": time.time(), "kind": "sell", "ticker": ticker, "side": p["side"], "price": str(bid),
                   "count": p["count"], "fee": str(fee), "pnl": str(pnl), "strategy_id": p["strategy_id"],
                   "title": p["title"], "actor": actor}
            self.history.append(row)
            self._save()
            return row

    def settle(self, ticker: str, result: str) -> Optional[dict]:
        """Market settled: winning side pays $1 per contract (no fee on settlement)."""
        with self._lock:
            p = self.positions.get(ticker)
            if not p or result not in ("yes", "no"):
                return None
            payout = D(p["count"]) if p["side"] == result else ZERO
            pnl = payout - (D(p["avg_price"]) * p["count"] + D(p["fees"]))
            self.cash += payout
            del self.positions[ticker]
            row = {"ts": time.time(), "kind": "settle", "ticker": ticker, "side": p["side"], "result": result,
                   "count": p["count"], "pnl": str(pnl), "strategy_id": p["strategy_id"], "title": p["title"],
                   "actor": "kalshi"}
            self.history.append(row)
            self._save()
            return row

    def reset(self):
        with self._lock:
            self.cash, self.positions, self.history = self.start_cash, {}, []
            self.auto.enabled = False
            self.log = [{"ts": time.time(), "msg": "Paper account reset to $%s" % self.start_cash}]
            self._save()

    def set_auto(self, **kw):
        with self._lock:
            for k, v in kw.items():
                if v is not None and k in AutopilotSettings.__dataclass_fields__:
                    setattr(self.auto, k, v)
            self._save()
            return asdict(self.auto)

    # ---- read model ------------------------------------------------------------------------
    def summary(self, quote: Callable[[str], tuple]) -> dict:
        """quote(ticker) -> (yes_bid, yes_ask) as Decimals or None."""
        with self._lock:
            rows, value, unreal = [], ZERO, ZERO
            for t, p in self.positions.items():
                yb, ya = quote(t)
                bid = yb if p["side"] == "yes" else (None if ya is None else ONE - ya)
                cost = D(p["avg_price"]) * p["count"] + D(p["fees"])
                mark = None if bid is None else bid * p["count"]
                upnl = None if mark is None else mark - cost
                value += mark if mark is not None else cost
                unreal += upnl or ZERO
                rows.append({**p, "bid": None if bid is None else str(bid), "cost": str(cost),
                             "value": None if mark is None else str(mark), "pnl": None if upnl is None else str(upnl)})
            realized = sum((D(h.get("pnl", "0")) for h in self.history if h["kind"] in ("sell", "settle")), ZERO)
            closed = [h for h in self.history if h["kind"] in ("sell", "settle")]
            wins = sum(1 for h in closed if D(h["pnl"]) > 0)
            at_risk = sum((D(r["cost"]) for r in rows), ZERO)
            return {"start_cash": str(self.start_cash), "cash": str(self.cash), "equity": str(self.cash + value),
                    "total_pnl": str(self.cash + value - self.start_cash), "realized": str(realized),
                    "unrealized": str(unreal), "at_risk": str(at_risk), "positions": rows,
                    "closed_trades": len(closed), "wins": wins,
                    "history": list(reversed(self.history[-50:])), "log": list(reversed(self.log[-60:])),
                    "autopilot": asdict(self.auto)}

    # ---- autopilot ---------------------------------------------------------------------------
    def autopilot_step(self, opportunities: list[dict]) -> list[dict]:
        """Paper-trade the best opportunities within the autopilot limits.  Returns the fills made."""
        a = self.auto
        if not a.enabled:
            return []
        made = []
        min_edge, max_trade, max_total = D(a.min_edge), D(a.max_trade_usd), D(a.max_total_usd)
        lo, hi = D(a.min_price), D(a.max_price)
        with self._lock:
            at_risk = sum((D(p["avg_price"]) * p["count"] + D(p["fees"]) for p in self.positions.values()), ZERO)
            for o in opportunities:
                if len(self.positions) >= a.max_positions:
                    break
                if a.strategies and o["strategy_id"] not in a.strategies:
                    continue
                if o["ticker"] in self.positions or o.get("edge") is None:
                    continue
                edge, price = D(o["edge"]), D(o["price"])
                if edge < min_edge or not (lo <= price <= hi):
                    continue
                budget = min(max_trade, max_total - at_risk, self.cash)
                count = int(budget / (price + D("0.02")))   # leave room for the fee
                if o.get("count"):
                    count = min(count, int(o["count"]))      # the model's own (Kelly) size is a ceiling
                if count < 1:
                    continue
                try:
                    row = self.buy(ticker=o["ticker"], side=o["side"], price=price, count=count,
                                   strategy_id=o["strategy_id"], title=o.get("title", ""), fair=o.get("fair"),
                                   actor="autopilot")
                except ValueError as e:
                    self.note(f"skipped {o['ticker']}: {e}")
                    continue
                at_risk += price * count + D(row["fee"])
                made.append(row)
                self.note(f"Bought {count} {o['side'].upper()} @ {int(price * 100)}¢ on {o.get('title') or o['ticker']}"
                          f" (edge {int(edge * 100)}¢, {o['strategy_id']})", ticker=o["ticker"])
        return made
