"""Bigger model on compressed history, judged only on seasons it never trained on.

    python -m kil_capital.research.deep --league nfl          # downloads nflverse once, then runs
    python -m kil_capital.research.deep --league all          # nfl, cfb, nba, nhl, mlb

Targets are the *market errors*: margin minus closing spread (ATS) and points minus closing total.
If the closing line is efficient the best prediction is 0, so the bar is honest: the model has to
predict where the market is wrong, on unseen seasons, by more than the -110 vig.

Walk-forward by season: for each test season, train on every earlier season only. Bet thresholds are
chosen on the first half of the test seasons and then *only reported* on the second half. Promotion:
the model goes live (feeds fair prices) only if its out-of-sample error beats the market-only baseline
by `PROMOTE_MARGIN` on the later half. Writes reports/DEEP_<LEAGUE>.md and data/deep_models.json."""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

from . import features, history, sources
from ..sports.segments import _wilson_low

WIN, LOSE = 100 / 110, -1.0                     # -110 pricing, push refunds
THRESHOLDS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)
EV_THRESHOLDS = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10)   # moneyline: expected profit per unit staked
PROMOTE_MARGIN = 0.01                           # RMSE points the model must save vs the market
PROMOTE_BRIER = 0.0005                          # moneyline: Brier score the model must save vs the market
FIRST_TEST = {"nfl": 2006, "cfb": 2012, "nba": 2014, "nhl": 2014, "mlb": 2014}
# Found by checking each source against facts any real market satisfies (home teams win ~53% in MLB;
# closing totals correlate ~0.2 with runs). A model that "beats" a broken line proves nothing.
DATA_WARNINGS = {"mlb": "DATA FAILED SANITY CHECKS - results below are NOT evidence of an edge. In this SBR "
                        "archive home teams win only 43% of games, 64% of moneyline pairs are impossible "
                        "(e.g. both sides favoured), and the closing total correlates only 0.10 with runs "
                        "(0.02 in 2018). Rows are misaligned between games, so any 'edge' is an artifact."}


def _gbm():
    return HistGradientBoostingRegressor(max_iter=250, learning_rate=0.03, max_leaf_nodes=15,
                                         min_samples_leaf=60, l2_regularization=1.0, random_state=0)


def walk_forward(X, y, seasons, first_test: int, make) -> np.ndarray:
    """Out-of-sample prediction for every game in seasons >= first_test (nan elsewhere)."""
    pred = np.full(len(y), np.nan)
    for s in sorted(set(seasons)):
        if s < first_test:
            continue
        tr, te = seasons < s, seasons == s
        ok = tr & ~np.isnan(y)
        if ok.sum() < 500 or not te.any():
            continue
        pred[te] = make().fit(X[ok], y[ok]).predict(X[te])
    return pred


def bets(pred, y, mask, t):
    """Bet the side the model favours when |pred| >= t. Returns n, wins, win rate, ROI at -110."""
    sel = mask & ~np.isnan(pred) & ~np.isnan(y) & (np.abs(pred) >= t)
    res = np.sign(pred[sel]) * y[sel]
    w, l = int((res > 0).sum()), int((res < 0).sum())
    n = w + l
    return {"t": t, "n": n, "wins": w, "win_rate": round(w / n, 4) if n else None,
            "win_low90": round(_wilson_low(w, n), 4) if n else None,
            "roi": round((w * WIN + l * LOSE) / n, 4) if n else None}


def rmse(p, y, mask):
    sel = mask & ~np.isnan(p) & ~np.isnan(y)
    return float(np.sqrt(np.mean((y[sel] - p[sel]) ** 2))) if sel.any() else math.nan


def _payout(ml):
    return ml / 100 if ml > 0 else 100 / -ml


def ml_bets(p_hat, meta, y, mask, t):
    """Bet the side whose expected profit at the real closing price is >= t. ROI at those prices."""
    n = w = 0
    profit = 0.0
    for i in np.flatnonzero(mask & ~np.isnan(p_hat) & ~np.isnan(y)):
        m, p = meta[i], p_hat[i]
        ev_h = p * _payout(m["ml_h"]) - (1 - p)
        ev_a = (1 - p) * _payout(m["ml_a"]) - p
        if max(ev_h, ev_a) < t or y[i] == 0.5:
            continue
        home = ev_h >= ev_a
        won = (y[i] == 1) == home
        n += 1
        w += won
        profit += _payout(m["ml_h"] if home else m["ml_a"]) if won else -1.0
    return {"t": t, "n": n, "wins": w, "win_rate": round(w / n, 4) if n else None,
            "win_low90": round(_wilson_low(w, n), 4) if n else None,
            "roi": round(profit / n, 4) if n else None}


def tune(rows, league, first_test) -> dict:
    """Search the hand-set feature settings around the league defaults. Scored by a ridge model's
    error on the selection seasons only (first half of the test window), never on the reported half."""
    base = features.LEAGUES[league]
    best, best_err, tried = base, math.inf, []
    for km in (0.5, 1.0, 2.0):
        for sm in (0.5, 1.0, 2.0):
            cfg = {**base, "k": base["k"] * km, "slow": base["slow"] * sm, "fast": min(0.6, base["fast"] * sm)}
            X, meta = features.build(rows, cfg)
            X = np.asarray(X, float)
            seasons = np.array([m["season"] for m in meta])
            test = sorted(x for x in set(seasons) if x >= first_test)
            sel = (seasons >= first_test) & (seasons < test[len(test) // 2])
            y = np.array([(m["margin"] - m["spread"]) if m["spread"] is not None else
                          ((m["margin"] > 0) - (m["mkt_p"] if m["mkt_p"] is not None else np.nan))
                          for m in meta], float)
            p = walk_forward(X, y, seasons, first_test, lambda: Ridge(alpha=10.0))
            err = rmse(p, y, sel)
            tried.append({"k": round(cfg["k"], 3), "slow": round(cfg["slow"], 4), "err": round(err, 5)})
            if err < best_err:
                best, best_err = cfg, err
    return {"cfg": best, "tried": tried}


def run(rows: list[dict], league: str, first_test: int, cfg: dict | None = None) -> dict:
    X, meta = features.build(rows, cfg)
    X = np.asarray(X, float)
    seasons = np.array([m["season"] for m in meta])
    has_line = np.array([m["spread"] is not None for m in meta])
    has_tot = np.array([m["total"] is not None for m in meta])
    y_ats = np.array([m["margin"] - m["spread"] if m["spread"] is not None else np.nan for m in meta])
    y_tot = np.array([m["points"] - m["total"] if m["total"] is not None else np.nan for m in meta])
    test_seasons = sorted(s for s in set(seasons) if s >= first_test)
    mid = test_seasons[len(test_seasons) // 2]
    early, late = (seasons >= first_test) & (seasons < mid), seasons >= mid
    out = {"league": league, "games": len(meta), "seasons": [int(seasons.min()), int(seasons.max())],
           "features": features.NAMES, "first_test": first_test, "select_on": [first_test, int(mid) - 1],
           "report_on": [int(mid), int(seasons.max())], "ts": time.time(), "markets": {}}
    for market, y, has in (("spread", y_ats, has_line), ("total", y_tot, has_tot)):
        models = {"gbm": walk_forward(X, y, seasons, first_test, _gbm),
                  "ridge": walk_forward(X, y, seasons, first_test, lambda: Ridge(alpha=10.0))}
        zero = np.where(np.isnan(models["gbm"]), np.nan, 0.0)
        res = {"market_rmse_late": round(rmse(zero, y, late & has), 3), "models": {}}
        for name, p in models.items():
            pick = max((bets(p, y, early & has, t) for t in THRESHOLDS),
                       key=lambda b: (b["roi"] if b["n"] >= 100 else -9))
            late_b = bets(p, y, late & has, pick["t"])
            r = rmse(p, y, late & has)
            res["models"][name] = {
                "rmse_late": round(r, 3), "beats_market": bool(r < res["market_rmse_late"] - PROMOTE_MARGIN),
                "chosen_threshold": pick["t"], "selection_window": pick, "unseen_window": late_b,
                "unseen_all_thresholds": [bets(p, y, late & has, t) for t in THRESHOLDS],
                "by_season": {int(s): bets(p, y, (seasons == s) & has, pick["t"]) for s in test_seasons}}
        res["promoted"] = [n for n, m in res["models"].items()
                           if m["beats_market"] and (m["unseen_window"]["roi"] or -1) > 0]
        out["markets"][market] = res
    # ---- moneyline: target = home win minus the de-vigged closing probability; bets at real prices ----
    has_ml = np.array([m["mkt_p"] is not None for m in meta])
    if has_ml.sum() > 2000:
        mp = np.array([m["mkt_p"] if m["mkt_p"] is not None else np.nan for m in meta])
        win = np.array([1.0 if m["margin"] > 0 else 0.0 if m["margin"] < 0 else 0.5 for m in meta])
        y_ml = np.where(has_ml, win - mp, np.nan)
        res = {"market_brier_late": round(rmse(np.where(has_ml, mp, np.nan), win, late & has_ml) ** 2, 5),
               "games_with_odds": int(has_ml.sum()), "models": {}}
        for name, make in (("gbm", _gbm), ("ridge", lambda: Ridge(alpha=10.0))):
            r_ = walk_forward(X, y_ml, seasons, first_test, make)
            p_hat = np.clip(mp + r_, 0.01, 0.99)
            pick = max((ml_bets(p_hat, meta, win, early & has_ml, t) for t in EV_THRESHOLDS),
                       key=lambda b: (b["roi"] if b["n"] >= 100 else -9))
            brier = rmse(p_hat, win, late & has_ml) ** 2
            res["models"][name] = {
                "brier_late": round(brier, 5),
                "beats_market": bool(brier < res["market_brier_late"] - PROMOTE_BRIER),
                "chosen_threshold": pick["t"], "selection_window": pick,
                "unseen_window": ml_bets(p_hat, meta, win, late & has_ml, pick["t"]),
                "unseen_all_thresholds": [ml_bets(p_hat, meta, win, late & has_ml, t) for t in EV_THRESHOLDS],
                "by_season": {int(s): ml_bets(p_hat, meta, win, (seasons == s) & has_ml, pick["t"])
                              for s in test_seasons}}
        res["promoted"] = [n for n, m in res["models"].items()
                           if m["beats_market"] and (m["unseen_window"]["roi"] or -1) > 0]
        out["markets"]["moneyline"] = res
    return out


def report(r: dict) -> str:
    L = [f"# Deep model: {r['league'].upper()}", "",
         f"{r['games']:,} games, seasons {r['seasons'][0]}-{r['seasons'][1]}, {len(r['features'])} point-in-time "
         f"features. Every prediction comes from a model trained only on earlier seasons. Thresholds chosen on "
         f"{r['select_on'][0]}-{r['select_on'][1]}; results below are on {r['report_on'][0]}-{r['report_on'][1]}, "
         "which the choice never saw. Bets are at -110 (52.4% to break even).", ""]
    if r["league"] in DATA_WARNINGS:
        L += [f"**{DATA_WARNINGS[r['league']]}**", ""]
    if r.get("tuning"):
        c = r["tuning"]["cfg"]
        L += [f"Feature settings were tuned on the selection seasons only: Elo K {c['k']:.3g}, slow decay "
              f"{c['slow']:.3g} (9 combinations tried).", ""]
    for mk, res in r["markets"].items():
        if mk == "moneyline":
            L += ["## Moneyline (target: win minus de-vigged closing probability; bets at the real closing price)", "",
                  f"{res['games_with_odds']:,} games with usable closing odds. Market-only Brier score on unseen "
                  f"seasons: {res['market_brier_late']}.", "",
                  "| Model | Brier | Beats market? | Min edge | Unseen bets | Win rate | Win rate, 90% low | ROI |",
                  "|---|---|---|---|---|---|---|---|"]
            for n, m in res["models"].items():
                u = m["unseen_window"]
                L.append(f"| {n} | {m['brier_late']} | {'yes' if m['beats_market'] else 'no'} | "
                         f"{m['chosen_threshold']:.0%} | {u['n']} | {u['win_rate']} | {u['win_low90']} | {u['roi']} |")
            L += ["", f"Promoted: {', '.join(res['promoted']) or 'none (the closing line stays the champion)'}", ""]
            continue
        L += [f"## {mk.title()} (target: result minus closing line)", "",
              f"Market-only error on unseen seasons: {res['market_rmse_late']} points.", "",
              "| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |",
              "|---|---|---|---|---|---|---|---|"]
        for n, m in res["models"].items():
            u = m["unseen_window"]
            L.append(f"| {n} | {m['rmse_late']} | {'yes' if m['beats_market'] else 'no'} | "
                     f"{m['chosen_threshold']} pts | {u['n']} | {u['win_rate']} | {u['win_low90']} | {u['roi']} |")
        L += ["", f"Promoted: {', '.join(res['promoted']) or 'none (the closing line stays the champion)'}", ""]
    L += [f"Two models x {len(r['markets'])} markets were tried, so one can look good by luck; a promoted model "
          "is trusted only after it keeps winning on new games logged by the app. Spread and total bets assume "
          "-110; moneyline bets use the actual closing price."]
    return "\n".join(L)


def load(league: str, raw: Path) -> list[dict]:
    if league == "nfl":
        return history.nflverse(raw)
    if league == "cfb":
        return sources.cfb(raw)
    if league in ("nba", "nhl", "mlb"):
        return sources.sbr(league, raw)
    raise SystemExit(f"No bulk public source with closing lines for {league!r}.")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="nfl")
    ap.add_argument("--data", default="data")
    ap.add_argument("--first-test", type=int, default=None)
    ap.add_argument("--no-tune", action="store_true")
    a = ap.parse_args(argv)
    for lg in (FIRST_TEST if a.league == "all" else [a.league]):
        rows = load(lg, Path(a.data) / "raw")
        ft = a.first_test or FIRST_TEST.get(lg, 2006)
        t = None if a.no_tune else tune(rows, lg, ft)
        r = run(rows, lg, ft, t["cfg"] if t else features.LEAGUES.get(lg))
        r["tuning"] = t
        Path("reports").mkdir(exist_ok=True)
        Path(f"reports/DEEP_{lg.upper()}.md").write_text(report(r))
        p = Path(a.data) / "deep_models.json"
        allr = json.loads(p.read_text()) if p.exists() else {}
        allr[lg] = r
        p.write_text(json.dumps(allr, indent=1, default=float))
        print(report(r), flush=True)


if __name__ == "__main__":
    main()
