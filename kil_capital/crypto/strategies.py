"""Long/flat spot strategies that retail and systematic crypto traders actually run.
Each takes oldest-first closes and returns a target position per bar in [0, 1], decided on that bar's
close and held over the NEXT bar (the backtester shifts it, so there is no look-ahead)."""
from __future__ import annotations

import math

from . import indicators as I


def _state(n, enter, exit_):
    pos, out = 0.0, [0.0] * n
    for i in range(n):
        if pos == 0 and enter(i):
            pos = 1.0
        elif pos == 1 and exit_(i):
            pos = 0.0
        out[i] = pos
    return out


def buy_hold(c):
    return [1.0] * len(c)


def trend_200(c, n=200):
    s = I.sma(c, n)
    return [1.0 if s[i] and c[i] > s[i] else 0.0 for i in range(len(c))]


def sma_cross(c, fast=20, slow=100):
    f, s = I.sma(c, fast), I.sma(c, slow)
    return [1.0 if s[i] and f[i] > s[i] else 0.0 for i in range(len(c))]


def macd_trend(c, fast=12, slow=26, sig=9):
    m = [a - b if a is not None and b is not None else None for a, b in zip(I.ema(c, fast), I.ema(c, slow))]
    start = next((i for i, v in enumerate(m) if v is not None), len(c))
    sl = [None] * start + I.ema(m[start:], sig) if start < len(c) else [None] * len(c)
    return [1.0 if m[i] is not None and sl[i] is not None and m[i] > sl[i] else 0.0 for i in range(len(c))]


def donchian(c, entry=20, exit_=10):
    hi, lo = I.rolling_max(c, entry), I.rolling_min(c, exit_)
    return _state(len(c), lambda i: i > 0 and hi[i - 1] is not None and c[i] > hi[i - 1],
                  lambda i: i > 0 and lo[i - 1] is not None and c[i] < lo[i - 1])


def tsmom(c, lookback=28, target_vol=0.40, bars_per_year=365):
    """Time-series momentum (Moskowitz-Ooi-Pedersen), long only, volatility-targeted."""
    vol = I.ewma_vol(I.log_returns(c))
    out = []
    for i in range(len(c)):
        if i < lookback or vol[i] is None or vol[i] == 0:
            out.append(0.0)
            continue
        on = c[i] > c[i - lookback]
        out.append(min(1.0, target_vol / (vol[i] * math.sqrt(bars_per_year))) if on else 0.0)
    return out


def rsi_reversion(c, n=14, lo=30, exit_at=55):
    r = I.rsi(c, n)
    return _state(len(c), lambda i: r[i] is not None and r[i] < lo, lambda i: r[i] is not None and r[i] > exit_at)


def rsi2_pullback(c):
    """Connors RSI(2): buy short-term dips only inside a long-term uptrend; exit on a bounce above SMA5."""
    r, s200, s5 = I.rsi(c, 2), I.sma(c, 200), I.sma(c, 5)
    return _state(len(c), lambda i: s200[i] and r[i] is not None and c[i] > s200[i] and r[i] < 10,
                  lambda i: s5[i] and c[i] > s5[i])


def bollinger_reversion(c, n=20, k=2.0):
    m, sd = I.sma(c, n), I.stdev(c, n)
    return _state(len(c), lambda i: sd[i] and c[i] < m[i] - k * sd[i], lambda i: m[i] and c[i] > m[i])


def trend_ensemble(c, target_vol=0.40, bars_per_year=365):
    """Average vote of five trend rules, then volatility-targeted: the diversified trend-follower's book."""
    votes = [trend_200(c), sma_cross(c), macd_trend(c), donchian(c), [1.0 if p > 0 else 0.0 for p in tsmom(c)]]
    vol = I.ewma_vol(I.log_returns(c))
    out = []
    for i in range(len(c)):
        v = sum(x[i] for x in votes) / len(votes)
        scale = min(1.0, target_vol / (vol[i] * math.sqrt(bars_per_year))) if vol[i] else 0.0
        out.append(v * scale)
    return out


STRATEGIES = {
    "buy_hold": ("Buy and hold", "Baseline: always long.", buy_hold),
    "trend_200": ("200-day trend filter", "Long above the 200-day average, cash below it.", trend_200),
    "sma_cross": ("20/100 moving-average cross", "Long while the 20-day average is above the 100-day.", sma_cross),
    "macd_trend": ("MACD trend", "Long while MACD(12,26) is above its 9-day signal.", macd_trend),
    "donchian": ("Donchian breakout (turtle)", "Buy a new 20-day high, sell a new 10-day low.", donchian),
    "tsmom": ("Time-series momentum, vol-targeted", "Long when price beats 4 weeks ago, sized to 40% annual vol.", tsmom),
    "trend_ensemble": ("Trend ensemble, vol-targeted", "Average of the five trend rules, sized to 40% annual vol.",
                       trend_ensemble),
    "rsi_reversion": ("RSI(14) oversold bounce", "Buy RSI under 30, sell above 55.", rsi_reversion),
    "rsi2_pullback": ("RSI(2) pullback in uptrend", "Connors: buy RSI(2) under 10 above the 200-day, sell above the 5-day.",
                      rsi2_pullback),
    "bollinger_reversion": ("Bollinger band reversion", "Buy a close below the lower band, sell at the middle.",
                            bollinger_reversion),
}
