"""Brute-force edge miner: every 1-, 2- and 3-condition rule over ~30 pre-game features, four leagues, judged three ways.

Seasons are cut in three, oldest to newest:
  discovery (first half)  -> a rule must win 56%+ with z >= 3 on 100+ bets
  validation (next quarter) -> it must still beat 52.4% on 40+ bets
  holdout (newest quarter)  -> looked at once, at the end; never used to choose anything
A shuffle test (outcomes permuted within season, same search) shows how many rules luck alone sends through.

Bets: home/away against the spread and over/under, at the closing line (features may use the open->close move,
which is known at close) and, where opening lines exist, at the opening line (features may NOT use the move).
Grading at -110 (break-even 52.4%). Recommend-only research; nothing here bets.
Run: PYTHONPATH=. python -m kil_capital.research.miner"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from kil_capital.research.deep import load
from kil_capital.research.new_ideas import add_form, add_rest, implied

RAW = Path("data/raw")
BE = 110 / 210
MOVE_FEATS = {"spread_move", "total_move", "abs_spread_move", "abs_total_move"}


# ---------------- features ----------------
def season_stats(rows):
    """Season-to-date per team (before the game): points for/against per game, win %, ATS %, over %."""
    acc = defaultdict(lambda: defaultdict(float))
    for r in sorted(rows, key=lambda r: r["ts"]):
        for side, t, o in ((1, r["home"], r["away"]), (-1, r["away"], r["home"])):
            a = acc[(r["season"], t)]
            g = a["g"]
            p = "h" if side == 1 else "a"
            r[f"g_{p}"] = g
            r[f"pf_{p}"] = a["pf"] / g if g else None
            r[f"pa_{p}"] = a["pa"] / g if g else None
            r[f"wp_{p}"] = a["w"] / g if g else None
            r[f"atsp_{p}"] = a["ats"] / a["atsn"] if a["atsn"] else None
            r[f"ovp_{p}"] = a["ov"] / a["ovn"] if a["ovn"] else None
        hs, as_ = r["hs"], r["as_"]
        for side, t in ((1, r["home"]), (-1, r["away"])):
            a = acc[(r["season"], t)]
            pf, pa = (hs, as_) if side == 1 else (as_, hs)
            a["g"] += 1
            a["pf"] += pf
            a["pa"] += pa
            a["w"] += pf > pa
            if r.get("spread") is not None:
                c = (hs - as_ - r["spread"]) * side
                if c:
                    a["ats"] += c > 0
                    a["atsn"] += 1
            if r.get("total"):
                c = hs + as_ - r["total"]
                if c:
                    a["ov"] += c > 0
                    a["ovn"] += 1
    return rows


def feats(r, at_open=False):
    """Pre-game features. At the opening line, every line feature uses the opening number: the closing spread,
    total and moneylines are not known yet when the opening line is bet."""
    f = {}
    so, to = r.get("spread_open"), r.get("total_open")
    sp, tot = (so, to) if at_open else (r.get("spread"), r.get("total"))
    f["spread"] = sp
    f["abs_spread"] = abs(sp) if sp is not None else None
    f["total"] = tot
    if not at_open and sp is not None and so is not None:
        f["spread_move"] = sp - so
        f["abs_spread_move"] = abs(sp - so)
    if not at_open and tot and to:
        f["total_move"] = tot - to
        f["abs_total_move"] = abs(tot - to)
    f["rest_h"] = r.get("rest_h") if r.get("rest_h") is not None else r.get("rh")
    f["rest_a"] = r.get("rest_a") if r.get("rest_a") is not None else r.get("ra")
    if f["rest_h"] is not None and f["rest_a"] is not None:
        f["rest_diff"] = min(f["rest_h"], 14) - min(f["rest_a"], 14)
    f["week_frac"] = r.get("g_h")
    for k in ("wp", "atsp", "ovp", "pf", "pa"):
        f[f"{k}_h"], f[f"{k}_a"] = r.get(f"{k}_h"), r.get(f"{k}_a")
    if r.get("wp_h") is not None and r.get("wp_a") is not None and min(r["g_h"], r["g_a"]) >= 3:
        f["wp_diff"] = r["wp_h"] - r["wp_a"]
        # simple points-based model: expected total and margin from season-to-date scoring
        et = (r["pf_h"] + r["pa_a"] + r["pf_a"] + r["pa_h"]) / 2
        em = (r["pf_h"] - r["pa_h"] - (r["pf_a"] - r["pa_a"])) / 2
        if tot:
            f["model_total_gap"] = et - tot
        if sp is not None:
            f["model_margin_gap"] = em - sp
    f["streak_h"], f["streak_a"] = r.get("st_h"), r.get("st_a")
    f["lastm_h"], f["lastm_a"] = r.get("pm_h"), r.get("pm_a")
    if not at_open and r.get("ml_h") and r.get("ml_a") and sp is not None:  # moneylines are closing prices
        f["ml_home_prob"] = implied(r["ml_h"]) / (implied(r["ml_h"]) + implied(r["ml_a"]))
    for k in ("temp", "wind"):
        f[k] = r.get(k)
    for k in ("div", "neutral", "dome", "playoff"):
        f[k] = float(bool(r.get(k)))
    return f


def outcomes(r, at_open):
    sk, tk = ("spread_open", "total_open") if at_open else ("spread", "total")
    sp, tot = r.get(sk), r.get(tk)
    m, s = r["hs"] - r["as_"], r["hs"] + r["as_"]
    o = {}
    if sp is not None:
        d = m - sp
        o["home ATS"], o["away ATS"] = (0, 0) if d == 0 else (1 if d > 0 else -1, 1 if d < 0 else -1)
    if tot:
        d = s - tot
        o["over"], o["under"] = (0, 0) if d == 0 else (1 if d > 0 else -1, 1 if d < 0 else -1)
    return o


TARGETS = ["home ATS", "away ATS", "over", "under"]


# ---------------- condition matrix ----------------
def build(lg, at_open):
    rows = season_stats(add_form(add_rest(load(lg, RAW))))
    if at_open:
        rows = [r for r in rows if r.get("spread_open") is not None or r.get("total_open")]
    rows.sort(key=lambda r: r["ts"])
    F = [feats(r, at_open) for r in rows]
    Y = np.zeros((len(rows), 4), dtype=np.int8)
    for i, r in enumerate(rows):
        o = outcomes(r, at_open)
        for j, t in enumerate(TARGETS):
            Y[i, j] = o.get(t, 0)
    seasons = np.array([r["season"] for r in rows])
    us = sorted(set(seasons))
    c1, c2 = us[len(us) // 2], us[(3 * len(us)) // 4]
    part = np.where(seasons < c1, 0, np.where(seasons < c2, 1, 2))
    names, cols = [], []
    keys = sorted({k for f in F for k in f if not (at_open and k in MOVE_FEATS)})
    for k in keys:
        v = np.array([np.nan if f.get(k) is None else float(f[k]) for f in F])
        disc = v[(part == 0) & ~np.isnan(v)]
        if len(disc) < 200:
            continue
        uniq = np.unique(disc)
        if len(uniq) <= 2:  # binary flag
            for val in uniq:
                names.append(f"{k} = {val:g}")
                cols.append(v == val)
            continue
        qs = np.unique(np.quantile(disc, [0.1, 0.2, 0.4, 0.6, 0.8, 0.9]))
        for q in qs[:3]:
            names.append(f"{k} <= {q:.3g}")
            cols.append(v <= q)
        for q in qs[-3:]:
            names.append(f"{k} >= {q:.3g}")
            cols.append(v >= q)
    C = np.array(cols, dtype=np.float32).T  # games x conditions
    return rows, C, names, Y, part, (us[0], c1, c2, us[-1])


# ---------------- search ----------------
def _Z(Y, part):
    """Stacked per-game indicators: for each target, wins/decided in discovery and in validation (n x 4 x 4)."""
    d, v = part == 0, part == 1
    w, n = Y == 1, Y != 0
    return np.stack([w & d[:, None], n & d[:, None], w & v[:, None], n & v[:, None]], axis=2).astype(np.float32)


def counts(C, Z):
    """K x K x 4 targets x 4 stats for every 1/2-condition rule over the given rows (diagonal = single condition)."""
    n, K = C.shape
    A = C.T @ (C[:, :, None] * Z.reshape(n, 1, 16)).reshape(n, K * 16)
    return A.reshape(K, K, 4, 4)


def zs(w, n):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(n > 0, (w / n - BE) / np.sqrt(BE * (1 - BE) / np.maximum(n, 1)), 0)


def search(C, Y, part, min_n=100, min_rate=0.56, min_z=3.0, triples=True):
    """Return candidate rules (tuple of condition idx, target idx) passing discovery, with validation stats."""
    keep = part < 2
    C, Y, part = C[keep], Y[keep], part[keep]
    Z = _Z(Y, part)
    K = C.shape[1]
    out = {}

    def take(S, extra):
        Wd, Nd, Wv, Nv = S[..., 0], S[..., 1], S[..., 2], S[..., 3]
        ok = (Nd >= min_n) & (Wd >= min_rate * Nd) & (zs(Wd, Nd) >= min_z)
        for idx in zip(*np.nonzero(ok)):
            *cond, t = idx
            key = (tuple(sorted(set(extra + tuple(int(c) for c in cond)))), int(t))
            if key not in out:
                out[key] = (Wd[idx], Nd[idx], Wv[idx], Nv[idx])

    take(counts(C, Z), ())
    if triples:
        dmask = part == 0
        for k in range(K):
            sel = C[:, k] > 0
            if (sel & dmask).sum() < min_n:
                continue
            take(counts(C[sel], Z[sel]), (k,))
    return out


def evaluate(C, Y, part, rules):
    res = []
    for (conds, t), (wd, nd, wv, nv) in rules.items():
        m = np.ones(len(Y), bool)
        for c in conds:
            m &= C[:, c] > 0
        y = Y[m & (part == 2), t]
        wh, nh = int((y == 1).sum()), int((y != 0).sum())
        res.append({"conds": conds, "t": t, "wd": int(wd), "nd": int(nd), "wv": int(wv), "nv": int(nv),
                    "wh": wh, "nh": nh})
    return res


def shuffled(Y, part, seasons_key, rng):
    Ys = Y.copy()
    for s in np.unique(seasons_key):
        idx = np.nonzero(seasons_key == s)[0]
        Ys[idx] = Y[rng.permutation(idx)]
    return Ys


def passes_val(r):
    return r["nv"] >= 40 and r["wv"] / r["nv"] > BE


def run_one(lg, at_open, rng, n_shuffle=20):
    rows, C, names, Y, part, cuts = build(lg, at_open)
    found = evaluate(C, Y, part, search(C, Y, part))
    val = [r for r in found if passes_val(r)]
    seas = np.array([r["season"] for r in rows])
    null = []
    for _ in range(n_shuffle):
        Ys = shuffled(Y, part, seas, rng)
        f2 = evaluate(C, Ys, part, search(C, Ys, part))
        null.append((len(f2), sum(passes_val(r) for r in f2)))
    pick = np.zeros(Y.shape, bool)
    for r in val:
        m = np.ones(len(Y), bool)
        for c in r["conds"]:
            m &= C[:, c] > 0
        pick[m & (part == 2), r["t"]] = True
    for a, b in ((0, 1), (2, 3)):  # a game picked on both sides of one market is not a bet
        both = pick[:, a] & pick[:, b]
        pick[both, a] = pick[both, b] = False
    yh = Y[pick]
    by_season = {}
    for i, j in zip(*np.nonzero(pick)):
        if Y[i, j]:
            s = rows[i]["season"]
            w, n = by_season.get(s, (0, 0))
            by_season[s] = (w + (Y[i, j] == 1), n + 1)
    return {"rows": len(rows), "K": len(names), "names": names, "cuts": cuts, "found": found, "val": val,
            "null": null, "uniq": (int((yh == 1).sum()), int((yh != 0).sum())), "by_season": by_season}


def fmt_rule(names, r):
    return " AND ".join(names[c] for c in r["conds"]) + f" -> {TARGETS[r['t']]}"


def cluster(val):
    """Many survivors are the same idea with slightly different cut-offs; keep the best per target+first feature."""
    best = {}
    for r in val:
        key = (r["t"], tuple(sorted({n.split(" ")[0] for n in r["feat_names"]})))
        if key not in best or r["nd"] * (r["wd"] / r["nd"] - BE) > best[key]["nd"] * (best[key]["wd"] / best[key]["nd"] - BE):
            best[key] = r
    return sorted(best.values(), key=lambda r: -(r["wv"] + r["wh"]) / max(r["nv"] + r["nh"], 1))


def main():
    rng = np.random.default_rng(7)
    L = ["# Brute-force edge search (2026-11-26)", "",
         "Every 1-, 2- and 3-condition rule over the pre-game features below, for home/away against the spread and "
         "over/under. Seasons are cut in three: **discovery** (oldest half) picks rules that won 56%+ with z 3+ on 100+ "
         "bets; **validation** (next quarter) keeps those still above 52.4%; **holdout** (newest quarter) is looked at "
         "once, at the end. The **shuffle test** runs the identical search on outcomes randomly reassigned within each "
         "season: it is how many rules luck alone sends through. A real edge shows up as more survivors than the "
         "shuffle AND a holdout win rate above 52.4%.", ""]
    summary = []
    for lg in ("nfl", "cfb", "nba", "nhl"):
        for at_open in (False, True):
            if at_open and lg == "nfl":
                continue  # nflverse has no opening lines
            tag = f"{lg.upper()} {'opening line' if at_open else 'closing line'}"
            R = run_one(lg, at_open, rng)
            for r in R["val"]:
                r["feat_names"] = [R["names"][c] for c in r["conds"]]
            cl = cluster(R["val"])
            hw = sum(r["wh"] for r in cl)
            hn = sum(r["nh"] for r in cl)
            nb = [b for _, b in R["null"]]
            uw, un = R["uniq"]
            nulls = f"median {int(np.median(nb))}, 90th percentile {int(np.percentile(nb, 90))}, max {max(nb)} survivors"
            s0, c1, c2, s1 = R["cuts"]
            L += [f"## {tag}", "",
                  f"{R['rows']} games, {R['K']} conditions. Discovery {s0}-{c1 - 1}, validation {c1}-{c2 - 1}, "
                  f"holdout {c2}-{s1}.", "",
                  f"* Real data: {len(R['found'])} rules pass discovery, {len(R['val'])} also pass validation "
                  f"({len(cl)} distinct ideas).",
                  f"* Shuffled data (20 runs, discovery->validation): {nulls}.",
                  f"* Distinct surviving ideas on the holdout, pooled: {hw}/{hn} = {hw / max(hn, 1):.1%}.",
                  f"* Every surviving rule on the holdout, each game counted once: {uw}/{un} = {uw / max(un, 1):.1%}"
                  + (" (by season: " + ", ".join(f"{s} {w}/{n}" for s, (w, n) in sorted(R['by_season'].items()))
                     + ")" if R["by_season"] else "") + ".", ""]
            if cl:
                L += ["| Rule | Discovery | Validation | Holdout |", "|---|---|---|---|"]
                for r in cl[:15]:
                    L.append(f"| {fmt_rule(R['names'], r)} | {r['wd']}/{r['nd']} {r['wd'] / r['nd']:.1%} | "
                             f"{r['wv']}/{r['nv']} {r['wv'] / r['nv']:.1%} | "
                             f"{r['wh']}/{r['nh']} {r['wh'] / max(r['nh'], 1):.1%} |")
                L.append("")
            null_val = np.mean([b for _, b in R["null"]])
            summary.append((tag, len(R["val"]), null_val, uw, un,
                            [(fmt_rule(R["names"], r), r) for r in cl if r["nh"] >= 30 and r["wh"] / r["nh"] > 0.55]))
            print(tag, len(R["found"]), len(R["val"]), sorted(b for _, b in R["null"]), f"uniq {uw}/{un}", R["by_season"], flush=True)
    L += ["## Verdict", "", "| Market | Survivors (real) | Survivors (luck, avg) | Holdout, each game once |", "|---|---|---|---|"]
    for tag, nv, nn, hw, hn, _ in summary:
        L.append(f"| {tag} | {nv} | {nn:.0f} | {hw}/{hn} = {hw / max(hn, 1):.1%} |")
    L += ["", "### Rules that also won 55%+ on the holdout (30+ bets)", ""]
    for tag, *_, good in summary:
        for txt, r in good:
            L.append(f"* {tag}: {txt} (discovery {r['wd'] / r['nd']:.1%} on {r['nd']}, validation "
                     f"{r['wv'] / r['nv']:.1%} on {r['nv']}, holdout {r['wh'] / r['nh']:.1%} on {r['nh']})")
    Path("reports").mkdir(exist_ok=True)
    Path("reports/EDGE_SEARCH.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[-40:]))


if __name__ == "__main__":
    main()
