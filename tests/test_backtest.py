import random
from decimal import Decimal as D

from kil_capital.backtest.data import normalise_candles, normalise_market
from kil_capital.backtest.engine import SimConfig, bh_adjust, run_backtest, simulate_fill, split_folds
from kil_capital.backtest.run import render_md
from kil_capital.strategies.base import Decision
from kil_capital.strategies.longshot import LongshotFade
from kil_capital.strategies.market_maker import MarketMaker

DAY = 86400.0


def synth(n=900, fav_win=0.93, seed=1, msu_every=0):
    rnd = random.Random(seed)
    t0 = 1_700_000_000.0
    out = []
    for i in range(n):
        close = t0 + i * (400 * DAY / n)
        yes_fav = rnd.random() < 0.5
        p = D("0.85")
        fav_wins = rnd.random() < fav_win
        res = ("yes" if fav_wins else "no") if yes_fav else ("no" if fav_wins else "yes")
        ya = p if yes_fav else D("1") - p + D("0.02")
        yb = ya - D("0.02")
        candles = [{"ts": close - h * 3600, "yes_bid": yb, "yes_ask": ya, "price": (ya + yb) / 2,
                    "price_low": yb - D("0.03"), "price_high": ya + D("0.03"), "volume": 500} for h in range(48, 0, -1)]
        title = "Mississippi State at Ole Miss" if (msu_every and i % msu_every == 0) else f"Team{i} at Team{i+1}"
        out.append({"ticker": f"KXNBAGAME-S{i}-A", "event_ticker": f"KXNBAGAME-S{i}", "series_ticker": "KXNBAGAME",
                    "category": "Sports", "title": title, "result": res, "open_ts": close - 3 * DAY, "close_ts": close,
                    "fee_type": "quadratic", "fee_multiplier": "1", "price_ranges": None, "candles": candles})
    return out


def test_folds_walk_forward_and_holdout():
    ms = synth(300)
    folds, pre, hold = split_folds(ms, SimConfig())
    assert folds and hold
    assert max(m["close_ts"] for m in pre) < min(m["close_ts"] for m in hold)
    for name, train, test in folds:
        assert max(m["close_ts"] for m in train) < min(m["close_ts"] for m in test)


def test_longshot_report_has_every_required_item():
    rep = run_backtest(LongshotFade(), synth(), SimConfig(bootstrap_n=300))
    assert rep["verdict"] in ("PASS", "INCONCLUSIVE", "FAIL")
    o = rep["oos"]
    for k in ("roi", "net_yield", "roi_ci95", "hit_rate", "avg_win", "avg_loss", "brier", "max_dd_usd",
              "max_dd_pct_alloc", "longest_under_water_days", "longest_losing_streak", "events", "bets",
              "clv_cents_mean", "top5_event_share_of_pnl", "median_bar_volume"):
        assert k in o, k
    for k in ("fees +10%", "fees x2", "latency 2x", "latency 5x", "maker fills 10%", "size 0.5x", "size 2x",
              "drop top 5 events", "holdout 1st half"):
        assert k in rep["robustness"]
    assert rep["folds"] and rep["holdout"]["bets"] > 0
    assert rep["equity_curve"] and rep["v4_bar"]
    assert o["roi"] > 0  # favourites priced 85c that win 93% must show a positive edge
    md = render_md(rep)
    assert "Walk-forward" in md and "go-live bar" in md


def test_msu_markets_allowed_since_block_lifted():
    ms = synth(400, msu_every=3)
    rep = run_backtest(LongshotFade(), ms, SimConfig(bootstrap_n=100), _robust=False)
    assert rep["universe_markets"] == 400


def test_no_data_and_no_trades():
    assert run_backtest(LongshotFade(), [], SimConfig())["verdict"] == "NO DATA"
    ms = synth(200)
    for m in ms:
        for c in m["candles"]:
            c["yes_bid"], c["yes_ask"] = D("0.48"), D("0.52")
    assert run_backtest(LongshotFade(), ms, SimConfig(bootstrap_n=50), _robust=False)["verdict"] == "NO TRADES"


def test_maker_fills_only_on_strict_trade_through():
    m = synth(1)[0]
    for c in m["candles"]:
        c["price_low"], c["price_high"] = D("0.50"), D("0.60")
    d = Decision(ts=m["close_ts"] - 10 * 3600, side="yes", price=D("0.50"), liquidity="maker", count=5)
    assert simulate_fill(m, d, SimConfig()) is None  # touch only: no fill
    m["candles"][-1]["price_low"] = D("0.49")
    assert simulate_fill(m, d, SimConfig()) is not None


def test_taker_fill_respects_latency_and_cap():
    m = synth(1)[0]
    t = m["candles"][10]["ts"]
    d = Decision(ts=t, side="yes", price=D("0.10"), count=1)
    assert simulate_fill(m, d, SimConfig()) is None  # ask above our cap
    d2 = Decision(ts=t, side="yes", price=D("0.99"), count=1)
    f = simulate_fill(m, d2, SimConfig())
    assert f[0] >= t + 2.0


def test_market_maker_runs():
    rep = run_backtest(MarketMaker(), synth(300), SimConfig(bootstrap_n=50), _robust=False)
    assert rep["verdict"] in ("NO TRADES", "INCONCLUSIVE", "FAIL", "PASS")


def test_bh():
    assert bh_adjust([0.01, 0.04, 0.03]) == [0.03, 0.04, 0.04]


def test_normalise_kalshi_shapes():
    raw = [{"end_period_ts": 100, "yes_bid": {"close_dollars": "0.40"}, "yes_ask": {"close": 45},
            "price": {"close_dollars": "0.42", "low_dollars": "0.40", "high_dollars": "0.44"}, "volume": "12"}]
    c = normalise_candles(raw)[0]
    assert c["yes_bid"] == D("0.40") and c["yes_ask"] == D("0.45") and c["volume"] == 12
    m = normalise_market({"ticker": "T", "result": "yes", "close_time": "2026-11-24T22:00:00Z"}, raw)
    assert m["result"] == "yes" and m["close_ts"] > 0
