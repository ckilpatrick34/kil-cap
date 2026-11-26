"""Round 3: strategy families never tested before in this project, each rule written down before looking.

Sports (graded on the later half of seasons, which plays the part of "unseen"):
  * NFL Wong teasers: 6-point, two-team at -120 (each leg must win 73.9%)
  * Moneyline price buckets (favourite-longshot bias) in NFL, NBA, NHL, MLB at real closing prices
  * Schedule spots: back-to-backs (NBA, NHL), bye/rest edge and short weeks (NFL)
  * Overreaction: fade long ATS streaks and fade teams after a blowout win
  * MLB systems (MLB was never in the line-system search): road dogs, big favourites, high/low totals
Crypto (selection 2016-2020, test 2021-on, next-day execution, 0.25% fee per side):
  * BTC/ETH relative-strength rotation, MVRV value scaling, network-activity momentum,
    exchange net outflow, weekend-only holding.

Recommend-only research: nothing here places a bet or an order.
Run: PYTHONPATH=. python -m kil_capital.research.new_ideas"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from kil_capital.research.deep import load
from kil_capital.research.lines import BE, ats, ou

RAW = Path("data/raw")


# ---------- grading helpers ----------
def split(rows):
    ss = sorted({r["season"] for r in rows})
    cut = ss[len(ss) // 2]
    return [r for r in rows if r["season"] < cut], [r for r in rows if r["season"] >= cut], cut


def z(w, n, p=BE):
    return (w / n - p) / math.sqrt(p * (1 - p) / n) if n else 0.0


def payout(ml):
    return ml / 100 if ml > 0 else 100 / -ml


def ml_res(r, side):
    """side +1 home, -1 away; returns profit per 1 unit staked at the closing moneyline, None if no price/tie."""
    ml = r.get("ml_h") if side == 1 else r.get("ml_a")
    if not ml or r["hs"] == r["as_"]:
        return None
    won = (r["hs"] > r["as_"]) == (side == 1)
    return payout(ml) if won else -1.0


def implied(ml):
    return -ml / (-ml + 100) if ml < 0 else 100 / (ml + 100)


def grade_ats(rows, pick):
    """pick(r) -> list of (result 0/1/None). Returns (n, wins)."""
    n = w = 0
    for r in rows:
        for x in pick(r) or []:
            if x is not None:
                n += 1
                w += x
    return n, w


def grade_ml(rows, pick):
    n, pnl, w = 0, 0.0, 0
    for r in rows:
        for s in pick(r) or []:
            x = ml_res(r, s)
            if x is not None:
                n += 1
                pnl += x
                w += x > 0
    return n, w, pnl


# ---------- schedule features ----------
def add_rest(rows):
    """Days since each team's previous game (NBA/NHL/MLB rows carry no rest field)."""
    last = {}
    for r in sorted(rows, key=lambda r: r["ts"]):
        for k, t in (("rh", r["home"]), ("ra", r["away"])):
            p = last.get(t)
            r[k] = None if p is None or r["ts"] - p > 20 * 86400 else round((r["ts"] - p) / 86400)
        last[r["home"]] = last[r["away"]] = r["ts"]
    return rows


def add_form(rows):
    """Per team: ATS cover streak and previous-game margin, both known before kickoff."""
    streak, prev = defaultdict(int), {}
    for r in sorted(rows, key=lambda r: r["ts"]):
        r["st_h"], r["st_a"] = streak[r["home"]], streak[r["away"]]
        r["pm_h"], r["pm_a"] = prev.get(r["home"]), prev.get(r["away"])
        m = r["hs"] - r["as_"]
        if r.get("spread") is not None:
            c = m - r["spread"]
            for t, s in ((r["home"], 1), (r["away"], -1)):
                if c * s > 0:
                    streak[t] = max(streak[t], 0) + 1
                elif c * s < 0:
                    streak[t] = min(streak[t], 0) - 1
        prev[r["home"]], prev[r["away"]] = m, -m
    return rows


# ---------- sports rule books ----------
def ats_rules(lg):
    B = {"nba": 20, "nfl": 21}.get(lg, 20)
    R = {}
    if lg in ("nba", "nhl"):
        R["rested team vs back-to-back (ATS)"] = lambda r: (
            [ats(r, 1)] if r.get("rh", 0) and r["rh"] >= 2 and r.get("ra") == 1 else
            [ats(r, -1)] if r.get("ra", 0) and r["ra"] >= 2 and r.get("rh") == 1 else None)
    if lg == "nfl":
        R["rest edge 3+ days (ATS)"] = lambda r: (
            [ats(r, 1 if r["rest_h"] > r["rest_a"] else -1)]
            if r.get("rest_h") and r.get("rest_a") and abs(r["rest_h"] - r["rest_a"]) >= 3 else None)
        R["fade road team on short week (ATS)"] = lambda r: (
            [ats(r, 1)] if r.get("rest_a") and r["rest_a"] <= 4 and (r.get("rest_h") or 7) >= 6 else None)
    R["fade 4+ game ATS cover streak"] = lambda r: [
        ats(r, -s) for s, st in ((1, r.get("st_h", 0)), (-1, r.get("st_a", 0))) if st >= 4] or None
    R["back 4+ game ATS losing streak"] = lambda r: [
        ats(r, s) for s, st in ((1, r.get("st_h", 0)), (-1, r.get("st_a", 0))) if st <= -4] or None
    R[f"fade team after {B}+ point win"] = lambda r: [
        ats(r, -s) for s, pm in ((1, r.get("pm_h")), (-1, r.get("pm_a"))) if pm is not None and pm >= B] or None
    R[f"back team after {B}+ point loss"] = lambda r: [
        ats(r, s) for s, pm in ((1, r.get("pm_h")), (-1, r.get("pm_a"))) if pm is not None and pm <= -B] or None
    return R


def ml_rules(lg):
    R = {}
    for lo, hi, name in ((0.0, 0.25, "longshots (25% or less)"), (0.25, 0.40, "dogs 25-40%"),
                         (0.60, 0.75, "favourites 60-75%"), (0.75, 1.0, "heavy favourites 75%+")):
        R[f"bet {name}"] = (lambda lo, hi: lambda r: [
            s for s, ml in ((1, r.get("ml_h")), (-1, r.get("ml_a"))) if ml and lo < implied(ml) <= hi])(lo, hi)
    R["home underdog ML"] = lambda r: [1] if r.get("ml_h") and r["ml_h"] > 100 else None
    R["road underdog ML"] = lambda r: [-1] if r.get("ml_a") and r["ml_a"] > 100 else None
    if lg in ("nhl", "mlb", "nba"):
        R["rested team vs back-to-back (ML)"] = lambda r: (
            [1] if r.get("rh", 0) and r["rh"] >= 2 and r.get("ra") == 1 else
            [-1] if r.get("ra", 0) and r["ra"] >= 2 and r.get("rh") == 1 else None)
    return R


def total_rules(lg):
    if lg != "mlb":
        return {}
    return {"MLB total 10+: under": lambda r: [ou(r, -1)] if (r.get("total") or 0) >= 10 else None,
            "MLB total 7 or less: over": lambda r: [ou(r, 1)] if 0 < (r.get("total") or 99) <= 7 else None}


# ---------- NFL Wong teasers ----------
def wong_legs(rows):
    """Teaser legs (+6): favourites -7.5..-8.5 -> -1.5..-2.5, dogs +1.5..+2.5 -> +7.5..+8.5. Spread = home margin."""
    legs = []
    for r in rows:
        sp = r.get("spread")
        if sp is None or r.get("playoff") is None:
            continue
        m = r["hs"] - r["as_"]
        for side in (1, -1):
            line = -sp * side  # the side's handicap as quoted (+ = getting points)
            if -8.5 <= line <= -7.5 or 1.5 <= line <= 2.5:
                d = side * m + line + 6
                legs.append((r["season"], r.get("week"), r["ts"], d > 0 if d != 0 else None, r.get("total")))
    return legs


def teaser_report(rows, cut):
    legs = [l for l in wong_legs(rows) if l[3] is not None]
    out = []
    for lab, f in (("all", lambda l: True), ("total 49 or less", lambda l: (l[4] or 0) <= 49)):
        for half, g in (("first half", lambda l: l[0] < cut), ("test half", lambda l: l[0] >= cut)):
            L = sorted([l for l in legs if f(l) and g(l)], key=lambda l: l[2])
            n, w = len(L), sum(l[3] for l in L)
            # pair legs in date order (two-team teasers as actually placeable that week)
            tick = [L[i][3] and L[i + 1][3] for i in range(0, len(L) - 1, 2)]
            tw, tn = sum(tick), len(tick)
            roi = (tw * 100 / 120 - (tn - tw)) / tn if tn else 0
            out.append((lab, half, n, w / n if n else 0, tn, tw / tn if tn else 0, roi))
    return out


# ---------- crypto ----------
def px(coin):
    d = pd.read_csv(RAW / f"cm_{coin}.csv",
                    usecols=["time", "PriceUSD", "CapMVRVCur", "AdrActCnt", "FlowInExUSD", "FlowOutExUSD"])
    d.index = pd.to_datetime(d.time)
    return d.drop(columns="time")


def run_pos(price, pos, fee=0.0025):
    """pos decided at close t, earns return t+1 -> t+2 (next-day execution)."""
    r = price.pct_change().fillna(0)
    p = pos.shift(2).fillna(0)
    cost = pos.diff().abs().shift(1).fillna(0) * fee
    return p * r - cost


def stats(ret):
    ret = ret.dropna()
    if len(ret) < 30:
        return None
    eq = (1 + ret).cumprod()
    yrs = len(ret) / 365
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    sh = ret.mean() / ret.std() * math.sqrt(365) if ret.std() else 0
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": cagr, "sharpe": sh, "maxdd": dd}


def crypto_rules():
    b, e = px("btc"), px("eth")
    idx = b.index.intersection(e.index)
    b, e = b.loc[idx], e.loc[idx]
    out = {}
    # 1. BTC/ETH relative strength rotation: hold whichever rose more over 28 days, only if it is above its 100-day avg
    mb, me = b.PriceUSD.pct_change(28), e.PriceUSD.pct_change(28)
    hold_b = (mb >= me) & (b.PriceUSD > b.PriceUSD.rolling(100).mean())
    hold_e = (me > mb) & (e.PriceUSD > e.PriceUSD.rolling(100).mean())
    rot = 0.0
    rot = run_pos(b.PriceUSD, hold_b.astype(float)) + run_pos(e.PriceUSD, hold_e.astype(float))
    out["BTC/ETH rotation (stronger coin, above 100d avg)"] = rot
    # 2. MVRV value scaling on BTC: full long under 1.0, scale down to zero at 3.5
    m = b.CapMVRVCur.ffill()
    out["BTC MVRV value scaling"] = run_pos(b.PriceUSD, ((3.5 - m) / 2.5).clip(0, 1).round(1))
    # 3. Network activity momentum: active addresses 30d avg above 90d avg AND price above 50d
    a = b.AdrActCnt.rolling(30).mean() > b.AdrActCnt.rolling(90).mean()
    out["BTC network-activity momentum"] = run_pos(b.PriceUSD, (a & (b.PriceUSD > b.PriceUSD.rolling(50).mean())).astype(float))
    # 4. Exchange net outflow (coins leaving exchanges = accumulation), 14-day sum
    nf = (b.FlowOutExUSD - b.FlowInExUSD).rolling(14).sum()
    out["BTC exchange net outflow"] = run_pos(b.PriceUSD, (nf > 0).astype(float))
    # 5. Weekend-only holding (Sat+Sun returns)
    wk = pd.Series((b.index.dayofweek >= 4).astype(float), index=b.index)  # decide Fri close -> hold Sat,Sun
    out["BTC weekend-only"] = run_pos(b.PriceUSD, wk)
    # baselines
    out["BTC buy and hold"] = run_pos(b.PriceUSD, pd.Series(1.0, index=b.index), fee=0)
    out["50/50 BTC+ETH buy and hold"] = 0.5 * run_pos(b.PriceUSD, pd.Series(1.0, index=idx), 0) + \
        0.5 * run_pos(e.PriceUSD, pd.Series(1.0, index=idx), 0)
    return out


# ---------- report ----------
def main():
    L = ["# Round 3: new strategy families (2026-11-26)", "",
         "Every rule below was written down before its results were looked at, and none was tested in earlier rounds.",
         "Sports seasons are split in half; the later half plays the part of seasons the rule never saw.",
         "Spread and total bets are graded at -110 (break-even 52.4%); moneylines at the real closing price.",
         "**Passes** = profitable in both halves, 150+ bets in the test half, test z-score 2+ (spreads) or test ROI "
         "above +3% (moneylines). About 60 rules are tested here, so expect two or three to look good by luck alone.", ""]
    passes = []
    for lg in ("nfl", "nba", "nhl", "mlb"):
        rows = add_form(add_rest(load(lg, RAW)))
        a, b, cut = split(rows)
        L += [f"## {lg.upper()} ({len(rows)} games, test half = seasons {cut} on)", "",
              "| Rule | First half | Test half | Test z / ROI | Pass |", "|---|---|---|---|---|"]
        for name, f in {**ats_rules(lg), **total_rules(lg)}.items():
            (n1, w1), (n2, w2) = grade_ats(a, f), grade_ats(b, f)
            if n1 + n2 == 0:
                continue
            ok = n1 and n2 >= 150 and w1 / n1 > BE and w2 / n2 > BE and z(w2, n2) >= 2 and lg != "mlb"
            passes += [f"{lg.upper()}: {name}"] if ok else []
            L.append(f"| {name} | {w1}/{n1} = {w1 / max(n1, 1):.1%} | {w2}/{n2} = {w2 / max(n2, 1):.1%} | "
                     f"z {z(w2, n2):+.1f} | {'YES' if ok else 'no'} |")
        for name, f in ml_rules(lg).items():
            (n1, _, p1), (n2, w2, p2) = grade_ml(a, f), grade_ml(b, f)
            if n1 + n2 == 0:
                continue
            ok = n1 and n2 >= 150 and p1 > 0 and p2 / n2 > 0.03
            passes += [f"{lg.upper()}: {name}"] if ok else []
            L.append(f"| {name} (ML) | ROI {p1 / max(n1, 1):+.1%} on {n1} | {w2}/{n2} won, ROI {p2 / max(n2, 1):+.1%} | "
                     f"ROI {p2 / max(n2, 1):+.1%} | {'YES' if ok else 'no'} |")
        if lg == "nfl":
            L += ["", "### NFL Wong teasers (6-point, two-team at -120; each leg must win 73.9% to break even)", "",
                  "| Filter | Half | Legs | Leg win % | Teasers | Teaser win % | ROI |", "|---|---|---|---|---|---|---|"]
            tr = teaser_report(rows, cut)
            for lab, half, n, lw, tn, tw, roi in tr:
                L.append(f"| {lab} | {half} | {n} | {lw:.1%} | {tn} | {tw:.1%} | {roi:+.1%} |")
            for lab in ("all", "total 49 or less"):
                h = [t for t in tr if t[0] == lab]
                if all(t[3] > 0.739 for t in h) and h[1][2] >= 150:
                    passes.append(f"NFL: Wong teasers ({lab})")
        if lg == "mlb":
            L += ["", "**MLB totals are a data error, not an edge.** The archive's MLB closing totals are corrupt: it lists "
                  "Cardinals at Pirates (2011) at 12.5 runs, a 'Pirates @ Pirates' game, and only 43 totals of 10+ at Coors "
                  "Field in 11 years. Bad lines regress to the real number, which makes 'under big totals, over small "
                  "totals' look like 58-60% winners. Both rules are excluded. MLB moneylines are unaffected."]
        L.append("")
    L += ["## Crypto (selection 2016-2020, test 2021 to May 2026)", "",
          "| Rule | Sel CAGR | Sel Sharpe | Test CAGR | Test Sharpe | Test max drawdown |", "|---|---|---|---|---|---|"]
    cr = crypto_rules()
    bh = stats(cr["BTC buy and hold"].loc["2021":])
    for k, ret in cr.items():
        s, t = stats(ret.loc["2016":"2020"]), stats(ret.loc["2021":])
        L.append(f"| {k} | {s['cagr']:+.0%} | {s['sharpe']:.2f} | {t['cagr']:+.0%} | {t['sharpe']:.2f} | {t['maxdd']:.0%} |")
        if "buy and hold" not in k and t["sharpe"] > bh["sharpe"] and t["maxdd"] > bh["maxdd"] and t["cagr"] > 0 \
                and s["sharpe"] > 0:
            passes.append(f"Crypto: {k} (test Sharpe {t['sharpe']:.2f} vs BTC hold {bh['sharpe']:.2f})")
    legs = [l for l in wong_legs(load("nfl", RAW)) if l[3] is not None and (l[4] or 0) <= 49]
    L += ["", "### Closest call: NFL Wong teasers by era (total 49 or less)", "",
          "| Seasons | Legs | Leg win % |", "|---|---|---|"]
    for lo, hi in ((1999, 2005), (2006, 2012), (2013, 2017), (2018, 2022), (2023, 2026)):
        x = [l for l in legs if lo <= l[0] <= hi]
        L.append(f"| {lo}-{hi} | {len(x)} | {sum(l[3] for l in x) / len(x):.1%} |")
    p_all = sum(l[3] for l in legs) / len(legs)
    L += ["", f"All years: {p_all:.1%} on {len(legs)} legs. Break-even is 73.9% at -120 and 76.8% at -130, so this is a "
          "thin edge only where two-team 6-point teasers are still -120, it is not statistically significant "
          f"(z {(p_all - .739) / math.sqrt(.739 * .261 / len(legs)):+.1f}), and Kalshi does not sell teasers.",
          "", "## What passed", ""] + ([f"* {p}" for p in passes] or ["* Nothing."]) + [""]
    Path("reports").mkdir(exist_ok=True)
    Path("reports/NEW_IDEAS.md").write_text("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
