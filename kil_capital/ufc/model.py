"""Logistic regression on A-minus-B fight features (numpy only, so it runs anywhere the publisher runs).

Fights are symmetric: each training bout is used in both orientations, so the model has no corner bias and
p(A beats B) = 1 - p(B beats A) exactly.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .history import FEATURES


class FightModel:
    def __init__(self, l2: float = 1.0):
        self.l2 = l2
        self.mu = self.sd = self.w = None

    def fit(self, X, y, weights=None):
        X, y = np.asarray(X, float), np.asarray(y, float)
        X = np.vstack([X, -X])
        y = np.concatenate([y, 1 - y])
        sw = np.ones(len(y)) if weights is None else np.concatenate([weights, weights])
        self.mu = np.zeros(X.shape[1])            # differences are already centred by symmetry
        self.sd = X.std(0) + 1e-9
        Z = X / self.sd
        w = np.zeros(Z.shape[1])
        for _ in range(60):                       # Newton steps, no intercept (symmetry)
            p = 1 / (1 + np.exp(-Z @ w))
            g = Z.T @ (sw * (p - y)) + self.l2 * w
            H = (Z * (sw * p * (1 - p))[:, None]).T @ Z + self.l2 * np.eye(len(w))
            step = np.linalg.solve(H, g)
            w -= step
            if np.abs(step).max() < 1e-8:
                break
        self.w = w
        return self

    def prob(self, X):
        Z = np.asarray(X, float) / self.sd
        return 1 / (1 + np.exp(-Z @ self.w))

    def to_json(self) -> dict:
        return {"features": list(FEATURES), "sd": self.sd.tolist(), "w": self.w.tolist(), "l2": self.l2}

    @classmethod
    def from_json(cls, d: dict) -> "FightModel":
        m = cls(d.get("l2", 1.0))
        m.sd, m.w = np.array(d["sd"]), np.array(d["w"])
        m.mu = np.zeros(len(m.w))
        return m

    def save(self, path: Path):
        path.write_text(json.dumps(self.to_json(), indent=1))


def logloss(p, y) -> float:
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def american_to_prob(odds: float) -> float:
    odds = float(odds)
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


def prob_to_american(p: float) -> int | None:
    if not p or p <= 0 or p >= 1:
        return None
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def devig(oa: float, ob: float) -> tuple[float, float]:
    a, b = american_to_prob(oa), american_to_prob(ob)
    return a / (a + b), b / (a + b)


def payout(odds: float) -> float:
    """Profit per $1 staked at American odds."""
    odds = float(odds)
    return odds / 100 if odds > 0 else 100 / -odds


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))
