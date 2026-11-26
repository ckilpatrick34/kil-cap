import time
from decimal import Decimal as D

from conftest import open_market, order, pf
from kil_capital.config import LimitError, RiskLimitsManager
from kil_capital.core.orders import Position
from kil_capital.core.risk import RiskEngine, StrategyCaps

import pytest


def fails(res):
    return [r.code for r in res if not r.ok]


def test_clean_order_passes_all_risk():
    r = RiskEngine().evaluate(order(), open_market(), pf())
    assert fails(r) == []


def test_fat_finger_tick_and_count():
    R = RiskEngine()
    assert "FAT_FINGER" in fails(R.evaluate(order(price=D("0.70")), open_market(), pf()))
    assert "PRICE_TICK" in fails(R.evaluate(order(price=D("0.505")), open_market(), pf()))
    assert "COUNT_VALID" in fails(R.evaluate(order(count=0), open_market(), pf()))


def test_max_order_loss():
    assert "MAX_ORDER_LOSS" in fails(RiskEngine().evaluate(order(count=499), open_market(), pf("100000")))


def test_per_market_and_event_caps():
    # NAV 1000: per market 5% = $50
    assert "PER_MARKET" in fails(RiskEngine().evaluate(order(count=120), open_market(), pf("1000")))


def test_daily_loss_and_drawdown():
    p = pf("10000", day_pnl=D("-600"))
    assert "DAILY_LOSS" in fails(RiskEngine().evaluate(order(), open_market(), p))
    p2 = pf("10000")
    p2.peak_nav = D("13000")
    assert "DRAWDOWN_KILL" in fails(RiskEngine().evaluate(order(), open_market(), p2))


def test_auto_kill_triggers():
    hits = []
    R = RiskEngine(on_auto_kill=hits.append)
    p = pf("10000", day_pnl=D("-501"))
    R.observe_portfolio(p)
    assert R.kill.tripped and "DAILY_LOSS" in hits[0]
    R2 = RiskEngine()
    for _ in range(5):
        R2.observe_venue_error()
    assert R2.kill.tripped
    R3 = RiskEngine()
    R3.observe_integrity("FEE_TYPE_CHANGE", "x")
    assert R3.kill.tripped


def test_drawdown_halve():
    p = pf("9000")
    p.peak_nav = D("10000")
    assert RiskEngine().size_multiplier(p) == D("0.5")
    assert RiskEngine().size_multiplier(pf()) == D("1")


def test_manual_cap():
    o = order(source="manual", strategy_id="pm_carson", count=1)
    assert "MANUAL_DAILY_CAP" in fails(RiskEngine().evaluate(o, open_market(), pf(manual_day_pnl=D("-100"))))


def test_strategy_starting_caps():
    R = RiskEngine()
    R.strategy_caps["longshot_fade"] = StrategyCaps(D("500"), 25, D("50"))
    assert "STRATEGY_MAX_CONTRACTS" in fails(R.evaluate(order(count=26), open_market(), pf()))
    assert "STRATEGY_DAILY_CAP" in fails(R.evaluate(order(count=1), open_market(),
                                                    pf(strategy_day_pnl={"longshot_fade": D("-50")})))


def test_team_and_cluster_caps():
    existing = Position("KXNBAGAME-X-LAL", "yes", 500, D("0.50"), teams=("LAL",), cluster="slate1", event_ticker="E1")
    p = pf("10000", positions=[existing])  # LAL exposure $250 vs team cap 3% = $300
    o = order(count=200, teams=("LAL",))
    assert "TEAM" in fails(RiskEngine().evaluate(o, open_market(), p))


def test_bankroll_at_risk_and_cash_floor():
    big = [Position(f"T{i}", "yes", 1000, D("0.50"), event_ticker=f"E{i}", category=f"C{i}") for i in range(12)]
    p = pf("10000", positions=big)
    p.cash = D("4000")
    f = fails(RiskEngine().evaluate(order(count=10), open_market(), p))
    assert "BANKROLL_AT_RISK" in f


def test_closing_order_not_blocked_by_exposure_caps():
    pos = Position("KXNBAGAME-26NOV24LALBOS-LAL", "yes", 120, D("0.50"))
    p = pf("1000", positions=[pos])
    r = RiskEngine().evaluate(order(action="sell", count=100), open_market(), p)
    assert "PER_MARKET" not in fails(r)


def test_crypto_window_and_stress():
    m = open_market("KXBTCD-26NOV2517-T95000", bid="0.90", ask="0.92")
    m.close_ts = time.time() + 30
    m.strike, m.strike_direction = D("95000"), "above"
    o = order(ticker=m.ticker, price=D("0.92"), count=10, desk="CRYPTO", asset="BTC")
    assert "CRYPTO_WINDOW" in fails(RiskEngine().evaluate(o, m, pf(spot={"BTC": D("100000")})))
    m.close_ts = time.time() + 3600
    # $5,000 NAV: 5% = $250 crypto cap. 250 contracts at 0.92 = $230 -> stress scenario BTC -15% loses all
    o2 = order(ticker=m.ticker, price=D("0.92"), count=200, desk="CRYPTO", asset="BTC")
    f = fails(RiskEngine().evaluate(o2, m, pf("5000", spot={"BTC": D("100000")})))
    assert "CRYPTO_EXPIRY" in f  # 1.5% per expiry = $75


def test_stress_math():
    R = RiskEngine()
    p = Position("KXBTCD-A", "yes", 100, D("0.90"), desk="CRYPTO", asset="BTC", strike=D("90000"), strike_direction="above")
    s = R.stress_losses([p], {"BTC": D("100000")})
    assert s["BTC -15% alone"] == D("90") and s["CPI shock: equities -3%, BTC -8%"] == 0


def test_limits_tighten_only():
    m = RiskLimitsManager()
    m.tighten("carson", max_order_contracts=100)
    assert m.current.max_order_contracts == 100
    with pytest.raises(LimitError):
        m.tighten("carson", max_order_contracts=200)
    with pytest.raises(LimitError):
        m.tighten("carson", daily_loss_frac="0.5")
