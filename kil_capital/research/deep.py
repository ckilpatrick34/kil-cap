"""Bigger model on compressed history, judged only on seasons it never trained on.

    python -m kil_capital.research.deep --league nfl          # downloads nflverse once, then runs

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

from . import features, history
from ..sports.segments import _wilson_low

WIN, LOSE = 100 / 110, -1.0                     # -110 pricing, push refunds
THRESHOLDS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)
PROMOTE_MARGIN = 0.01                           # RMSE points the model must save vs the market


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


def run(rows: list[dict], league: str, first_test: int) -> dict:
    X, meta = features.build(rows)
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
    return out


def report(r: dict) -> str:
    L = [f"# Deep model: {r['league'].upper()}", "",
         f"{r['games']:,} games, seasons {r['seasons'][0]}-{r['seasons'][1]}, {len(r['features'])} point-in-time "
         f"features. Every prediction comes from a model trained only on earlier seasons. Thresholds chosen on "
         f"{r['select_on'][0]}-{r['select_on'][1]}; results below are on {r['report_on'][0]}-{r['report_on'][1]}, "
         "which the choice never saw. Bets are at -110 (52.4% to break even).", ""]
    for mk, res in r["markets"].items():
        L += [f"## {mk.title()} (target: result minus closing line)", "",
              f"Market-only error on unseen seasons: {res['market_rmse_late']} points.", "",
              "| Model | Error | Beats market? | Threshold | Unseen bets | Win rate | Win rate, 90% low | ROI |",
              "|---|---|---|---|---|---|---|---|"]
        for n, m in res["models"].items():
            u = m["unseen_window"]
            L.append(f"| {n} | {m['rmse_late']} | {'yes' if m['beats_market'] else 'no'} | "
                     f"{m['chosen_threshold']} pts | {u['n']} | {u['win_rate']} | {u['win_low90']} | {u['roi']} |")
        L += ["", f"Promoted: {', '.join(res['promoted']) or 'none (the closing line stays the champion)'}", ""]
    L += ["Two models x two markets were tried, so one of four can look good by luck; a promoted model is "
          "trusted only after it keeps winning on new games logged by the app."]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="nfl")
    ap.add_argument("--data", default="data")
    ap.add_argument("--first-test", type=int, default=2006)
    a = ap.parse_args(argv)
    if a.league != "nfl":
        raise SystemExit("Only nfl has a bulk public source here; other leagues train from ESPN history in-app.")
    rows = history.nflverse(Path(a.data) / "raw")
    r = run(rows, a.league, a.first_test)
    Path("reports").mkdir(exist_ok=True)
    Path(f"reports/DEEP_{a.league.upper()}.md").write_text(report(r))
    p = Path(a.data) / "deep_models.json"
    allr = json.loads(p.read_text()) if p.exists() else {}
    allr[a.league] = r
    p.write_text(json.dumps(allr, indent=1, default=float))
    print(report(r))


if __name__ == "__main__":
    main()
