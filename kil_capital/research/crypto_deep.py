"""Crypto strategy research on long, free daily histories, judged only on years the rules never saw.

Data (fetched once into data/raw/, never committed):
  * BTC: Bitstamp 1-minute candles 2012-today (github ff137/bitstamp-btcusd-minute-data) -> data/raw/btc_1d.parquet
  * ETH, LTC, XRP, DOGE + BTC on-chain (MVRV): Coin Metrics community CSVs (github coinmetrics/data)

Rules are fixed in advance (popular, published before 2021).  Selection years 2016-2020, test years 2021-on.
A rule "wins" only if, on the test years, it beats buy-and-hold on Sharpe AND on max drawdown with positive CAGR.
Recommend-only research: nothing here trades."""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

from kil_capital.crypto.backtest import luck_p
from kil_capital.crypto.strategies import STRATEGIES

RAW = Path("data/raw")
TEST_START = "2021-01-01"
SEL_START = "2016-01-01"
COINS = ["btc", "eth", "ltc", "xrp", "doge"]
RULES = ["trend_200", "sma_cross", "donchian", "tsmom", "trend_ensemble", "rsi2_pullback"]


def load() -> dict[str, pd.Series]:
    out = {}
    b = pd.read_parquet(RAW / "btc_1d.parquet").close
    b.index = b.index.tz_localize(None).normalize()
    out["btc"] = b
    for c in COINS[1:]:
        d = pd.read_csv(RAW / f"cm_{c}.csv", usecols=["time", "PriceUSD"]).dropna()
        out[c] = pd.Series(d.PriceUSD.values, index=pd.to_datetime(d.time))
    return out


def mvrv() -> pd.Series:
    d = pd.read_csv(RAW / "cm_btc.csv", usecols=["time", "CapMVRVCur"]).dropna()
    return pd.Series(d.CapMVRVCur.values, index=pd.to_datetime(d.time))


def bt(px: pd.Series, pos: pd.Series, fee: float) -> pd.Series:
    """Daily returns: position decided at today's close, held tomorrow; fee on every change."""
    pos = pos.reindex(px.index).fillna(0)
    held = pos.shift(1).fillna(0)
    return held * px.pct_change().fillna(0) - (held - held.shift(1).fillna(0)).abs() * fee


def stats(r: pd.Series) -> dict:
    if len(r) < 30:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / 365
    sd = r.std()
    return {"cagr": eq.iloc[-1] ** (1 / yrs) - 1, "sharpe": r.mean() / sd * math.sqrt(365) if sd else 0.0,
            "max_dd": float((1 - eq / eq.cummax()).max()), "total": eq.iloc[-1] - 1}


def wins(s: dict, bh: dict) -> bool:
    # snip:prod — the pass/fail rule is the honesty boundary; keep it strict
    return bool(s) and s["cagr"] > 0 and s["sharpe"] > bh["sharpe"] and s["max_dd"] < bh["max_dd"]


def rotation(px: dict[str, pd.Series], target_vol=0.40) -> pd.DataFrame:
    """Hold every coin above its 200-day average, inverse-volatility weighted, gross scaled to target vol, cap 100%."""
    df = pd.DataFrame(px).sort_index().ffill(limit=3)
    on = df > df.rolling(200, min_periods=200).mean()
    vol = np.log(df).diff().ewm(alpha=0.06).std() * math.sqrt(365)
    w = (on / vol).where(on, 0).fillna(0)
    w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    port_vol = (w * vol.fillna(0)).sum(axis=1)  # conservative: assumes correlation 1
    return w.mul((target_vol / port_vol.replace(0, np.nan)).clip(upper=1).fillna(0), axis=0)


def run(fee: float) -> tuple[list[dict], dict]:
    px = load()
    rows = []
    for coin, s in px.items():
        s = s[s.index >= "2014-01-01"]
        c = s.tolist()
        bh = {p: stats(bt(s, pd.Series(1.0, index=s.index), fee)[lambda r: _win(r, p)]) for p in ("sel", "test")}
        rows.append({"coin": coin, "rule": "buy_hold", **{f"{p}_{k}": v for p in bh for k, v in bh[p].items()},
                     "win": None})
        for rule in RULES:
            pos = pd.Series(STRATEGIES[rule][2](c), index=s.index)
            r = bt(s, pos, fee)
            st = {p: stats(_win_r(r, p)) for p in ("sel", "test")}
            rows.append({"coin": coin, "rule": rule, **{f"{p}_{k}": v for p in st for k, v in st[p].items()},
                         "win": wins(st["test"], bh["test"]),
                         "luck_p": luck_p(c, pos.tolist(), stats(r).get("sharpe"), fee, n=60)})
    # multi-coin rotation vs equal-weight buy-and-hold of the same coins
    w = rotation(px)
    rets = pd.DataFrame(px).sort_index().ffill(limit=3).pct_change()
    held = w.shift(1).fillna(0)
    port = (held * rets.fillna(0)).sum(axis=1) - (held.diff().abs().sum(axis=1)) * fee
    ew = rets.mean(axis=1, skipna=True).fillna(0)
    extra = {"rotation": {p: stats(_win_r(port, p)) for p in ("sel", "test")},
             "equal_weight_hold": {p: stats(_win_r(ew, p)) for p in ("sel", "test")}}
    # BTC trend + on-chain overheating filter (MVRV > 3.5 = historically late-cycle)
    b = px["btc"][px["btc"].index >= "2014-01-01"]
    t200 = pd.Series(STRATEGIES["trend_200"][2](b.tolist()), index=b.index)
    m = mvrv().reindex(b.index).ffill()
    r = bt(b, t200.where(m < 3.5, 0.0), fee)
    extra["btc_trend_mvrv"] = {p: stats(_win_r(r, p)) for p in ("sel", "test")}
    return rows, extra


def _win(r, p):
    return (r.index >= SEL_START) & (r.index < TEST_START) if p == "sel" else r.index >= TEST_START


def _win_r(r, p):
    return r[_win(r, p)]


def report(fee: float) -> str:
    rows, extra = run(fee)
    df = pd.DataFrame(rows)
    pct = lambda x: f"{x:+.0%}" if isinstance(x, float) and x == x else "-"
    lines = [f"# Crypto strategies on unseen years (fee {fee:.2%} per side)", "",
             f"Selection years {SEL_START[:4]}-2020, test years {TEST_START[:4]}-latest. Win = test-year CAGR > 0, "
             "Sharpe above buy-and-hold AND smaller max drawdown.", "",
             "| coin | rule | test CAGR | test Sharpe | test max DD | sel Sharpe | luck p | win |",
             "|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        lines.append(f"| {r.coin} | {r.rule} | {pct(r.test_cagr)} | {r.test_sharpe:.2f} | {r.test_max_dd:.0%} | "
                     f"{r.sel_sharpe:.2f} | {r.get('luck_p', '-') if r.rule != 'buy_hold' else '-'} | "
                     f"{'-' if r.win is None else ('YES' if r.win else 'no')} |")
    lines += ["", "| portfolio | test CAGR | test Sharpe | test max DD | sel CAGR | sel Sharpe |", "|---|---|---|---|---|---|"]
    for k, v in extra.items():
        t, s = v["test"], v["sel"]
        lines.append(f"| {k} | {pct(t['cagr'])} | {t['sharpe']:.2f} | {t['max_dd']:.0%} | {pct(s['cagr'])} | {s['sharpe']:.2f} |")
    by_rule = df[df.rule != "buy_hold"].groupby("rule").win.sum().sort_values(ascending=False)
    lines += ["", "Coins won per rule (of 5): " + ", ".join(f"{k} {int(v)}" for k, v in by_rule.items())]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fee", type=float, default=0.0025)
    print(report(ap.parse_args().fee))


if __name__ == "__main__":
    main()
