"""Lean on the market: fair = w * model + (1 - w) * Kalshi mid, with w learned from graded picks.

Why: a model whose probabilities are too close to 50% (under-dispersed) makes cheap underdogs look like
edges.  Shrinking toward the live market price fixes that; how much to trust the model over the market is
then learned nightly from our own settled picks, and a new weight is kept only if it beats the current one
in log loss on the most recent picks it was not fitted on."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

DEFAULT_W = 0.5          # trust the model half, the market half, until our record says otherwise
GRID = [round(0.1 * i, 1) for i in range(1, 11)]
MIN_N, MARGIN = 60, 0.002


def load(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def weight(path: Path) -> float:
    return float(load(path).get("w", DEFAULT_W))


def blend(model_p: float, mid: float | None, w: float) -> float:
    return model_p if mid is None else w * model_p + (1 - w) * mid


def _ll(rows: list[dict], w: float) -> float:
    s = 0.0
    for r in rows:
        p = min(max(blend(r["model_fair"], r["mid"], w), 1e-4), 1 - 1e-4)
        s -= math.log(p if r["won"] else 1 - p)
    return s / len(rows)


def deciles(rows: list[dict], key: str = "fair") -> list[dict]:
    """Predicted vs actual hit rate in ten price bands: the calibration chart."""
    out = []
    for i in range(10):
        lo, hi = i / 10, (i + 1) / 10
        b = [r for r in rows if lo <= r[key] < hi or (i == 9 and r[key] == 1)]
        if b:
            out.append({"band": f"{int(lo*100)}-{int(hi*100)}", "n": len(b),
                        "predicted": round(sum(r[key] for r in b) / len(b), 3),
                        "actual": round(sum(r["won"] for r in b) / len(b), 3)})
    return out


def fit(rows: list[dict], current: float = DEFAULT_W) -> dict:
    """rows: settled picks with model_fair, mid (both for the side taken), won, ts.  Walk-forward:
    choose w on the older 70%, then keep it only if it beats `current` on the newest 30%."""
    rows = sorted((r for r in rows if r.get("model_fair") is not None and r.get("mid") is not None),
                  key=lambda r: r["ts"])
    res = {"ts": time.time(), "n": len(rows), "w": current, "promoted": False}
    if len(rows) < MIN_N:
        res["reason"] = f"{len(rows)} graded picks with market data, need {MIN_N}"
        return res
    cut = int(len(rows) * 0.7)
    tune, hold = rows[:cut], rows[cut:]
    best = min(GRID, key=lambda w: _ll(tune, w))
    c_ll, n_ll = _ll(hold, current), _ll(hold, best)
    res.update(challenger=best, champion_logloss=round(c_ll, 4), challenger_logloss=round(n_ll, 4),
               holdout_n=len(hold))
    if best != current and n_ll < c_ll - MARGIN:
        res.update(w=best, promoted=True)
    else:
        res["reason"] = "new weight did not beat the current one on the newest picks"
    return res
