"""Nightly self-learning: retrain on settled games, promote a new model only if it wins on games it never saw.

Walk-forward, no peeking:
  * Games are split by date into a TUNE window and a later HOLDOUT window (last `holdout_days`).
  * Every prediction is made from ratings fitted only on games played before that prediction's week.
  * Candidate settings (home edge, recency half-life, ridge strength) are scored on TUNE only.
  * The best candidate (challenger) and the live settings (champion) are then both scored on HOLDOUT,
    which tuning never touched. The challenger replaces the champion only if it beats it there by
    `margin` in log loss on at least `min_holdout` games.
  * Sigmas are re-estimated from out-of-sample residuals; the model-vs-book blend weight is re-fitted
    on HOLDOUT games that had a pre-game book line.
Champion settings live in data/model_params.json, every run is appended to data/learn_log.json."""
from __future__ import annotations

import dataclasses
import itertools
import json
import math
import time
from pathlib import Path

from .leagues import LEAGUES, League
from .ratings import fit, norm_cdf

TUNABLE = ("hfa", "halflife_days", "sigma_margin", "sigma_total", "w_model")
DAY = 86400


def effective(key: str, params: dict | None) -> tuple[League, float]:
    """League constants with the learned champion settings applied, plus the ridge strength."""
    p = (params or {}).get(key, {})
    lg = dataclasses.replace(LEAGUES[key], **{k: p[k] for k in TUNABLE if k in p})
    return lg, float(p.get("lam", 2.0))


def load(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def _settled(games: list[dict]) -> list[dict]:
    return sorted((g for g in games if g.get("start_ts") is not None
                   and g["home"].get("score") is not None and g["away"].get("score") is not None),
                  key=lambda g: g["start_ts"])


def predictions(lg: League, lam: float, games: list[dict], start_ts: float, end_ts: float,
                step_days: int = 7) -> list[dict]:
    """Out-of-sample predictions for games in [start_ts, end_ts): refit weekly on earlier games only."""
    out, t = [], start_ts
    while t < end_ts:
        past = [g for g in games if g["start_ts"] < t]
        week = [g for g in games if t <= g["start_ts"] < min(t + step_days * DAY, end_ts)]
        t += step_days * DAY
        if len(past) < 30 or not week:
            continue
        R = fit(lg, past, t, lam=lam)
        for g in week:
            h, a = g["home"]["id"], g["away"]["id"]
            if h not in R.margin or a not in R.margin:
                continue
            m = R.margin[h] - R.margin[a] + (0 if g["neutral"] else lg.hfa)
            tot = 2 * R.base + R.off[h] + R.deff[a] + R.off[a] + R.deff[h]
            out.append({"m": m, "t": tot, "am": g["home"]["score"] - g["away"]["score"],
                        "at": g["home"]["score"] + g["away"]["score"],
                        "bm": -g["odds"]["spread_home"] if (g.get("odds") or {}).get("spread_home") is not None
                        else None})
    return out


def sigmas(preds: list[dict], lg: League) -> tuple[float, float]:
    if len(preds) < 30:
        return lg.sigma_margin, lg.sigma_total
    sm = math.sqrt(sum((p["am"] - p["m"]) ** 2 for p in preds) / len(preds))
    st = math.sqrt(sum((p["at"] - p["t"]) ** 2 for p in preds) / len(preds))
    return round(sm, 2), round(st, 2)


def logloss(preds: list[dict], sigma: float) -> float:
    if not preds:
        return float("inf")
    s = 0.0
    for p in preds:
        q = min(1 - 1e-6, max(1e-6, norm_cdf(p["m"] / sigma)))
        won = p["am"] > 0 if p["am"] != 0 else None
        if won is None:              # ties (NHL shootouts are scored as wins by ESPN, so rare)
            continue
        s -= math.log(q if won else 1 - q)
    return s / len(preds)


def fit_w_model(preds: list[dict], default: float) -> float:
    """Blend weight on our model vs the book line that minimises margin error on unseen games."""
    rows = [p for p in preds if p["bm"] is not None]
    if len(rows) < 40:
        return default
    grid = [i / 20 for i in range(21)]
    return min(grid, key=lambda w: sum((w * p["m"] + (1 - w) * p["bm"] - p["am"]) ** 2 for p in rows))


def score(lg: League, lam: float, games: list[dict], a: float, b: float) -> tuple[float, list[dict]]:
    preds = predictions(lg, lam, games, a, b)
    sm, _ = sigmas(preds, lg)
    return logloss(preds, sm), preds


def learn_league(key: str, games: list[dict], champion: dict | None = None, holdout_days: int = 21,
                 margin: float = 0.002, min_holdout: int = 40, grid: dict | None = None) -> dict:
    games = _settled(games)
    base = LEAGUES[key]
    champion = champion or {}
    res = {"league": key, "n_games": len(games), "promoted": False, "ts": time.time()}
    if len(games) < 120:
        res["reason"] = "not enough settled games yet"
        return res
    first, last = games[0]["start_ts"], games[-1]["start_ts"] + 1
    split = last - holdout_days * DAY
    tune_start = first + 0.35 * (split - first)          # need a warm-up season chunk before predicting
    grid = grid or {"hfa": [base.hfa * f for f in (0.6, 1.0, 1.4)],
                    "halflife_days": [base.halflife_days * f for f in (0.5, 1.0, 2.0)],
                    "lam": [1.0, 2.0, 5.0]}
    best = None
    for hfa, hl, lam in itertools.product(grid["hfa"], grid["halflife_days"], grid["lam"]):
        lg = dataclasses.replace(base, hfa=hfa, halflife_days=hl)
        ll, _ = score(lg, lam, games, tune_start, split)
        if best is None or ll < best[0]:
            best = (ll, {"hfa": round(hfa, 3), "halflife_days": round(hl, 1), "lam": lam})
    champ_lg, champ_lam = effective(key, {key: champion})
    chal_lg, chal_lam = effective(key, {key: {**champion, **best[1]}})
    c_ll, c_preds = score(champ_lg, champ_lam, games, split, last)
    n_ll, n_preds = score(chal_lg, chal_lam, games, split, last)
    res.update(holdout_n=len(n_preds), champion_logloss=round(c_ll, 4), challenger_logloss=round(n_ll, 4),
               challenger=best[1], tune_logloss=round(best[0], 4))
    if len(n_preds) < min_holdout:
        res["reason"] = f"holdout has {len(n_preds)} games, need {min_holdout}"
        return res
    if n_ll >= c_ll - margin:
        res["reason"] = "challenger did not beat champion on unseen games"
        return res
    sm, st = sigmas(n_preds, chal_lg)
    res["promoted"] = True
    res["params"] = {**best[1], "sigma_margin": sm, "sigma_total": st,
                     "w_model": fit_w_model(n_preds, chal_lg.w_model), "promoted_ts": res["ts"]}
    return res


def nightly(espn, data_dir: Path, today, leagues: list[str] | None = None) -> list[dict]:
    """Retrain every league on settled results; persist champions and the run log."""
    data_dir = Path(data_dir)
    params_path, log_path = data_dir / "model_params.json", data_dir / "learn_log.json"
    params, results = load(params_path), []
    for key in leagues or list(LEAGUES):
        try:
            r = learn_league(key, espn.history(LEAGUES[key], today), params.get(key))
        except Exception as e:  # one league failing must not stop the others
            r = {"league": key, "promoted": False, "reason": f"error: {e}", "ts": time.time()}
        if r.get("promoted"):
            params[key] = {**params.get(key, {}), **r["params"]}
        results.append(r)
    params_path.write_text(json.dumps(params, indent=1))
    log = load(log_path) if log_path.exists() else []
    log = (log if isinstance(log, list) else []) + results
    log_path.write_text(json.dumps(log[-500:], indent=1))
    return results
