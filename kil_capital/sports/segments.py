"""Segments, sizing and the honest 60%-win-rate search.

A *segment* is league x market x edge bucket x favourite/underdog. Every graded pick (Big Vin's history or
our own track record) lands in one. Segment ROI is shrunk toward zero (`PRIOR` pseudo-picks at ROI 0) so a
hot 20-pick streak can't move sizing much, then turned into a stake multiplier:
    shrunk ROI <= -3%  -> 0   (segment is skipped)
    otherwise          -> 1 + 4 * shrunk ROI, clipped to [0.5, 1.5]

Sizing is fractional Kelly on the fee-inclusive cost, times the segment multiplier, capped by max_trade.
Recommendations are ranked by expected profit in dollars (what "max profit" means), with ROI alongside."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

PRIOR = 150
KELLY_FRACTION = 0.25          # full Kelly is too aggressive when fair prices carry model error


def taker_fee(p: float) -> float:
    return 0.07 * p * (1 - p)


def edge_bucket(edge: float) -> str:
    return "<3c" if edge < 0.03 else "3-5c" if edge < 0.05 else "5-10c" if edge < 0.10 else "10c+"


def side_of(price: float) -> str:
    return "fav" if price >= 0.5 else "dog"


def key(league: str, kind: str, edge: float, price: float) -> str:
    return f"{league}|{kind}|{edge_bucket(edge)}|{side_of(price)}"


def build_table(picks: list[dict], prior: int = PRIOR) -> dict:
    """picks: dicts with league, kind, edge, price (0-1 cost), won (bool), stake (default 1)."""
    agg = defaultdict(lambda: {"n": 0, "w": 0, "staked": 0.0, "pnl": 0.0})
    for p in picks:
        stake = p.get("stake") or 1.0
        c = p["price"] + taker_fee(p["price"])
        a = agg[key(p["league"], p["kind"], p["edge"], p["price"])]
        a["n"] += 1
        a["w"] += bool(p["won"])
        a["staked"] += stake
        a["pnl"] += stake * ((1 - c) / c if p["won"] else -1)
    out = {}
    for k, a in agg.items():
        roi = a["pnl"] / a["staked"]
        shrunk = roi * a["n"] / (a["n"] + prior)
        mult = 0.0 if shrunk <= -0.03 else max(0.5, min(1.5, 1 + 4 * shrunk))
        out[k] = {"n": a["n"], "win_rate": round(a["w"] / a["n"], 3), "roi": round(roi, 4),
                  "shrunk_roi": round(shrunk, 4), "mult": round(mult, 3)}
    return out


def load_table(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def size(fair: float, price: float, equity: float, max_trade: float, mult: float = 1.0,
         frac: float = KELLY_FRACTION) -> dict:
    """Fractional-Kelly stake on the fee-inclusive cost; expected profit and ROI of that stake."""
    c = price + taker_fee(price)
    f = max(0.0, (fair - c) / (1 - c)) if c < 1 else 0.0
    stake = min(max_trade, frac * f * mult * equity)
    count = int(stake / c) if c > 0 else 0
    roi = (fair - c) / c if c > 0 else 0.0
    return {"stake": round(count * c, 2), "count": count, "kelly_full": round(f, 4), "mult": mult,
            "roi": round(roi, 4), "exp_profit": round(count * (fair - c), 2)}


# ---------- the 60% search ----------

def _wilson_low(w: int, n: int, z: float = 1.645) -> float:
    if n == 0:
        return 0.0
    p = w / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def winrate_search(picks: list[dict], min_n: int = 30, target: float = 0.60, train_frac: float = 0.7) -> dict:
    """Find segments that hit `target` win rate on the first 70% of picks (by time), then report how they
    did on the last 30% they were not chosen on. Win rate is shown WITH ROI, because a 70% favourite at 80c
    loses money. Only segments that also hold up out of sample, and are profitable there, are 'credible'."""
    picks = sorted(picks, key=lambda p: p.get("ts", 0))
    cut = int(len(picks) * train_frac)
    train, test = picks[:cut], picks[cut:]
    by_tr, by_te = defaultdict(list), defaultdict(list)
    for p in train:
        by_tr[key(p["league"], p["kind"], p["edge"], p["price"])].append(p)
    for p in test:
        by_te[key(p["league"], p["kind"], p["edge"], p["price"])].append(p)
    tested = sum(1 for ps in by_tr.values() if len(ps) >= min_n)
    rows = []
    for k, ps in by_tr.items():
        if len(ps) < min_n:
            continue
        w = sum(p["won"] for p in ps)
        if w / len(ps) < target:
            continue
        te = by_te.get(k, [])
        tw = sum(p["won"] for p in te)
        t_tab = build_table(te, prior=0).get(k) if te else None
        rows.append({"segment": k, "train_n": len(ps), "train_win": round(w / len(ps), 3),
                     "train_roi": build_table(ps, prior=0)[k]["roi"],
                     "test_n": len(te), "test_win": round(tw / len(te), 3) if te else None,
                     "test_win_low90": round(_wilson_low(tw, len(te)), 3) if te else None,
                     "test_roi": t_tab["roi"] if t_tab else None,
                     "credible": bool(te and len(te) >= min_n // 2 and _wilson_low(tw, len(te)) >= target
                                      and t_tab and t_tab["roi"] > 0)})
    rows.sort(key=lambda r: (not r["credible"], -(r["test_roi"] or -9)))
    return {"segments_tested": tested, "hits": rows, "credible": [r for r in rows if r["credible"]],
            "note": f"{tested} segments were tested, so some will clear {target:.0%} by luck; only the "
                    "out-of-sample columns count."}
