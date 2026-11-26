"""Classic indicators, pure Python, oldest-first lists.  None until enough history."""
from __future__ import annotations

import math


def sma(x, n):
    out, s = [None] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(x, n):
    out, k, e = [None] * len(x), 2 / (n + 1), None
    for i, v in enumerate(x):
        e = v if e is None else e + k * (v - e)
        out[i] = e if i >= n - 1 else None
    return out


def rsi(x, n=14):
    """Wilder's RSI."""
    out = [None] * len(x)
    if len(x) <= n:
        return out
    gains = [max(0.0, x[i] - x[i - 1]) for i in range(1, n + 1)]
    losses = [max(0.0, x[i - 1] - x[i]) for i in range(1, n + 1)]
    ag, al = sum(gains) / n, sum(losses) / n
    for i in range(n, len(x)):
        if i > n:
            d = x[i] - x[i - 1]
            ag = (ag * (n - 1) + max(0.0, d)) / n
            al = (al * (n - 1) + max(0.0, -d)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def stdev(x, n):
    out = [None] * len(x)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        m = sum(w) / n
        out[i] = math.sqrt(sum((v - m) ** 2 for v in w) / (n - 1))
    return out


def rolling_max(x, n):
    return [max(x[i - n + 1:i + 1]) if i >= n - 1 else None for i in range(len(x))]


def rolling_min(x, n):
    return [min(x[i - n + 1:i + 1]) if i >= n - 1 else None for i in range(len(x))]


def log_returns(x):
    return [0.0] + [math.log(x[i] / x[i - 1]) for i in range(1, len(x))]


def ewma_vol(rets, lam=0.94):
    """RiskMetrics EWMA volatility per bar."""
    out, var = [None] * len(rets), None
    for i, r in enumerate(rets):
        var = r * r if var is None else lam * var + (1 - lam) * r * r
        out[i] = math.sqrt(var) if i >= 20 else None
    return out
