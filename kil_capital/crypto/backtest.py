"""Honest backtests: next-bar execution, fees on every change of position, out-of-sample holdout,
and a parameter-free verdict.  Nothing here is fit to the holdout."""
from __future__ import annotations

import math
import random

from .strategies import STRATEGIES

FEE_PER_SIDE = 0.0025   # 0.25%: a mid-tier taker fee plus slippage on a liquid USD pair


def run(closes: list[float], pos: list[float], fee: float = FEE_PER_SIDE) -> dict:
    eq, curve, prev, turnover, trades = 1.0, [1.0], 0.0, 0.0, 0
    rets = []
    for i in range(1, len(closes)):
        p = pos[i - 1]                       # decided on yesterday's close
        cost = abs(p - prev) * fee
        if p > 0 and prev == 0:
            trades += 1
        turnover += abs(p - prev)
        r = p * (closes[i] / closes[i - 1] - 1) - cost
        eq *= 1 + r
        rets.append(r)
        curve.append(eq)
        prev = p
    return {"rets": rets, "curve": curve, "trades": trades, "turnover": turnover,
            "exposure": sum(1 for x in pos[:-1] if x > 0) / max(1, len(pos) - 1)}


def metrics(rets: list[float], bars_per_year: int = 365) -> dict:
    n = len(rets)
    if n < 2:
        return {"cagr": None, "sharpe": None, "max_dd": None, "vol": None}
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    mu = sum(rets) / n
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (n - 1))
    years = n / bars_per_year
    return {"cagr": eq ** (1 / years) - 1 if eq > 0 else -1.0, "sharpe": mu / sd * math.sqrt(bars_per_year) if sd else 0.0,
            "max_dd": mdd, "vol": sd * math.sqrt(bars_per_year), "total": eq - 1}


def evaluate(closes: list[float], holdout: float = 0.4, fee: float = FEE_PER_SIDE) -> dict:
    """Every strategy on the full history; metrics split into the first 60% (in-sample) and last 40% (out-of-sample)."""
    cut = int(len(closes) * (1 - holdout))
    out = {}
    for key, (name, desc, fn) in STRATEGIES.items():
        pos = fn(closes)
        bt = run(closes, pos, fee)
        out[key] = {"name": name, "desc": desc, "position": round(pos[-1], 3),
                    "in_sample": metrics(bt["rets"][:cut]), "out_of_sample": metrics(bt["rets"][cut:]),
                    "full": metrics(bt["rets"]), "trades": bt["trades"], "exposure": round(bt["exposure"], 3),
                    "avg_hold_days": round(bt["exposure"] * (len(closes) - 1) / bt["trades"], 1) if bt["trades"] else None,
                    "curve": [round(x, 4) for x in bt["curve"][::max(1, len(bt["curve"]) // 200)]]}
    for key, r in out.items():
        if key != "buy_hold":
            r["luck_p"] = luck_p(closes, STRATEGIES[key][2](closes), r["full"]["sharpe"], fee)
    bh = out["buy_hold"]["out_of_sample"]
    for k, r in out.items():
        r["verdict"] = verdict(r, bh) if k != "buy_hold" else "baseline"
    return out


def luck_p(closes, pos, sharpe, fee, n=100, block=20, seed=7) -> float:
    """Share of random timings (same exposure, positions shuffled in 20-bar blocks) that did at least as well.
    Small = the edge is unlikely to be luck."""
    if sharpe is None:
        return 1.0
    rng = random.Random(seed)
    blocks = [pos[i:i + block] for i in range(0, len(pos), block)]
    beat = 0
    for _ in range(n):
        rng.shuffle(blocks)
        sh = metrics(run(closes, [x for b in blocks for x in b], fee)["rets"])["sharpe"] or 0
        beat += sh >= sharpe
    return beat / n


def verdict(r: dict, bh: dict) -> str:
    """'keep' only if it held up out-of-sample: positive Sharpe in BOTH halves, at least 15 trades, beats 90% of
    random timings with the same exposure, and either a better Sharpe than buy-and-hold or a much smaller drawdown
    for a comparable Sharpe."""
    i, o = r["in_sample"], r["out_of_sample"]
    if not o["sharpe"] or not i["sharpe"] or o["sharpe"] <= 0.3 or i["sharpe"] <= 0.3:
        return "drop"
    if r["trades"] < 15 or r.get("luck_p", 1) > 0.10:
        return "watch"
    if o["sharpe"] >= (bh["sharpe"] or 0) or (o["max_dd"] < 0.6 * bh["max_dd"] and o["sharpe"] >= 0.8 * (bh["sharpe"] or 0)):
        return "keep"
    return "watch"
