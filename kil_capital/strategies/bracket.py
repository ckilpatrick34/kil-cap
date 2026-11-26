"""S1 / CR1 bracket_arb: intra-Kalshi complete-set arbitrage (spec v4 §3.2 A, §4.3).

Scanner: for an event whose markets are mutually exclusive and exhaustive, buying YES on every
bracket costs sum(asks) + fees and pays exactly $1.  Buying NO on every bracket of an N-bracket
set pays N-1.  Also checks monotone threshold ladders (P(>K1) >= P(>K2) for K1 < K2).

Rules: riskless ONLY if the rules match.  The whole event is skipped if any leg is blocked
(MSU) or if the event is not flagged mutually exclusive.  Leg risk is real: the gateway's
S1 naked-leg cap (min($100, 1% NAV) for <=10 s) applies when executing.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from ..core import blocklist, money
from .base import Signal, Strategy, live_book

D = Decimal


def complete_set_edge(markets: list[dict], fee_type="quadratic", mult=D("1")):
    """Return (kind, edge_per_set, legs) for the best complete-set trade, or None."""
    asks, bids = [], []
    for m in markets:
        yb, ya = live_book(m)
        if ya is None or yb is None or not (D("0") < ya < D("1")) or not (D("0") < yb < D("1")):
            return None
        asks.append(ya)
        bids.append(yb)
    n = len(markets)
    try:
        fee_yes = sum(money.fee(a, 1, fee_type=fee_type, multiplier=mult, liquidity="taker") for a in asks)
        fee_no = sum(money.fee(D("1") - b, 1, fee_type=fee_type, multiplier=mult, liquidity="taker") for b in bids)
    except money.FeeUnknown:
        return None
    buy_yes = D("1") - sum(asks) - fee_yes
    buy_no = D(n - 1) - sum(D("1") - b for b in bids) - fee_no
    best = max((buy_yes, "buy_all_yes", asks), (buy_no, "buy_all_no", [D("1") - b for b in bids]), key=lambda x: x[0])
    return best[1], best[0], best[2]


def ladder_violations(markets: list[dict]):
    """Monotone threshold ladder: for 'above K' markets, yes_bid(K_hi) must not exceed yes_ask(K_lo)."""
    rungs = []
    for m in markets:
        if m.get("strike_type") in ("greater", "greater_or_equal") and m.get("floor_strike") is not None:
            yb, ya = live_book(m)
            rungs.append((D(str(m["floor_strike"])), yb, ya, m))
    rungs.sort(key=lambda r: r[0])
    out = []
    for (k1, _, a1, m1), (k2, b2, _, m2) in zip(rungs, rungs[1:]):
        if a1 is not None and b2 is not None and b2 > a1:
            out.append({"buy": m1["ticker"], "sell": m2["ticker"], "gap": b2 - a1})
    return out


class BracketArb(Strategy):
    id = "bracket_arb"
    name = "Complete-set / ladder arbitrage"
    catalog_id = "S1/CR1"
    evidence = "PROVEN as math (only if rules match)"
    status = "backtesting"
    structural = True
    notes = ("Bar: zero rules-mismatch losses and positive net on every historical instance (300-event rule "
             "waived). Backtest needs synchronized books per event; candle data cannot prove it -> recorder (Phase 3).")

    @classmethod
    def default_params(cls):
        return {"min_edge": D("0.01"), "contracts": 5}

    def scan(self, markets, now=None):
        by_event = defaultdict(list)
        for m in markets:
            by_event[m.get("event_ticker")].append(m)
        out = []
        for ev, ms in by_event.items():
            if not ev or len(ms) < 2:
                continue
            if blocklist.event_excluded(ms):   # whole-event exclusion (§2.4)
                continue
            if all(m.get("mutually_exclusive") or m.get("_event_mutually_exclusive") for m in ms):
                r = complete_set_edge(ms)
                if r and r[1] >= self.params["min_edge"]:
                    kind, edge, prices = r
                    side = "yes" if kind == "buy_all_yes" else "no"
                    for m, p in zip(ms, prices):
                        out.append(Signal(self.id, m["ticker"], side, p, None, edge,
                                          f"{kind} on {ev}: edge ${edge:.4f}/set", {"event": ev, "legs": len(ms)}, m))
            for v in ladder_violations(ms):
                out.append(Signal(self.id, v["buy"], "yes", D("0"), None, v["gap"],
                                  f"ladder violation vs {v['sell']} gap {v['gap']}", v, {}))
        return out

    def intents(self, signals, size_mult=D("1")):
        # Ladder-violation signals are informational (price 0) until a two-leg executor exists.
        return super().intents([s for s in signals if s.price > 0], size_mult)
