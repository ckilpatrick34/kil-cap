"""Risk checks with reason codes, and the kill switch (spec v4 §2.3 step 1, §4.4, §7).

`RiskEngine.evaluate(order, market, portfolio)` returns every check result in a fixed order.
The gateway rejects on the first failure but the ticket preview shows them all.
The SAME code is used by the backtester (§6.1 "same code as live").
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Iterable, Optional

from ..config import RiskLimits, RiskLimitsManager
from . import money
from .orders import MarketInfo, OrderIntent, PortfolioState, Position

D = Decimal
ZERO = D("0")

CRYPTO_MACRO_DESKS = {"CRYPTO", "ECON"}
INDEX_ASSETS = ("SPX", "NDX", "INX", "NASDAQ")

# §4.4 stress scenarios: per-asset fractional moves.  Crypto assets other than BTC move like BTC
# (conservative); equity indices use the equity shock.
STRESS_SCENARIOS = {
    "BTC -15% alone": {"crypto": D("-0.15"), "equity": D("0")},
    "Nasdaq -5% & BTC -12%": {"crypto": D("-0.12"), "equity": D("-0.05")},
    "CPI shock: equities -3%, BTC -8%": {"crypto": D("-0.08"), "equity": D("-0.03")},
}


@dataclass
class CheckResult:
    code: str
    ok: bool
    detail: str = ""

    def as_dict(self):
        return {"code": self.code, "ok": self.ok, "detail": self.detail}


@dataclass
class KillSwitch:
    tripped: bool = False
    reason: str = ""
    ts: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def trip(self, reason: str) -> bool:
        with self._lock:
            if self.tripped:
                return False
            self.tripped, self.reason, self.ts = True, reason, time.time()
            return True

    def reset(self, phrase: str) -> bool:
        if phrase != "RESET KILL SWITCH":
            return False
        with self._lock:
            self.tripped, self.reason, self.ts = False, "", 0.0
        return True


@dataclass
class StrategyCaps:
    """§7.3 per-strategy live caps (set at enable)."""
    exposure_usd: Decimal
    max_contracts: int
    daily_loss_usd: Decimal


def _order_increment(order: OrderIntent, portfolio: PortfolioState, fee: Decimal) -> Decimal:
    """Incremental worst-case loss this order adds.  Closing an existing position adds 0."""
    if order.action == "sell":
        held = sum(p.count for p in portfolio.positions if p.ticker == order.ticker and p.side == order.side)
        if held >= order.count:
            return ZERO
    return money.max_loss(order.side, order.action, order.price, order.count, fee)


def _bought(order: OrderIntent) -> tuple[str, Decimal]:
    return money.cost_basis(order.side, order.action, order.price, order.count)


class RiskEngine:
    def __init__(self, limits: RiskLimitsManager | None = None, kill: KillSwitch | None = None,
                 on_auto_kill: Optional[Callable[[str], None]] = None, clock=time.time):
        self.limits_mgr = limits or RiskLimitsManager()
        self.kill = kill or KillSwitch()
        self.on_auto_kill = on_auto_kill
        self.strategy_caps: dict[str, StrategyCaps] = {}
        self.clock = clock
        self.venue_errors: list[float] = []

    @property
    def L(self) -> RiskLimits:
        return self.limits_mgr.current

    # ---- automatic kill triggers -----------------------------------------------------
    def auto_kill(self, reason: str):
        if self.kill.trip(reason) and self.on_auto_kill:
            self.on_auto_kill(reason)

    def observe_portfolio(self, pf: PortfolioState):
        """Run automatic triggers: drawdown kill (built) and daily loss cap (v4 addition)."""
        if pf.peak_nav > 0 and (pf.peak_nav - pf.nav) / pf.peak_nav >= self.L.drawdown_kill_frac:
            self.auto_kill(f"DRAWDOWN_KILL: NAV {pf.nav} is >= {self.L.drawdown_kill_frac:%} below peak {pf.peak_nav}")
        if pf.start_of_day_nav > 0 and -pf.day_pnl >= pf.start_of_day_nav * self.L.daily_loss_frac:
            self.auto_kill(f"DAILY_LOSS: day P&L {pf.day_pnl} breached {self.L.daily_loss_frac:%} of start NAV")
        for asset, age in (pf.spot_age_s or {}).items():
            if self._has_crypto_exposure(pf, asset) and age > self.L.spot_feed_gap_kill_s:
                self.auto_kill(f"SPOT_FEED_GAP: {asset} spot feed silent {age:.0f}s")

    def observe_venue_error(self, n_in_window=5, window_s=60):
        now = self.clock()
        self.venue_errors = [t for t in self.venue_errors if now - t < window_s] + [now]
        if len(self.venue_errors) >= n_in_window:
            self.auto_kill(f"VENUE_ERRORS: {len(self.venue_errors)} errors in {window_s}s")

    def observe_integrity(self, kind: str, detail: str):
        """Data-integrity failures (stale book, fee-type change, rules-text change)."""
        self.auto_kill(f"DATA_INTEGRITY:{kind}: {detail}")

    @staticmethod
    def _has_crypto_exposure(pf, asset):
        return any(p.asset == asset for p in pf.positions)

    def size_multiplier(self, pf: PortfolioState) -> Decimal:
        """§7.1 drawdown halve: -10% from peak halves all bot sizes."""
        if pf.peak_nav > 0 and (pf.peak_nav - pf.nav) / pf.peak_nav >= self.L.drawdown_halve_frac:
            return D("0.5")
        return D("1")

    # ---- exposure aggregation ----------------------------------------------------------
    @staticmethod
    def _book(pf: PortfolioState) -> list[Position]:
        return list(pf.positions) + list(pf.resting)

    def exposures(self, pf: PortfolioState) -> dict:
        agg = {k: defaultdict(lambda: ZERO) for k in
               ("market", "event", "category", "cluster", "team", "player", "league",
                "settlement_source", "strategy", "expiry")}
        total = ZERO
        cm = ZERO
        for p in self._book(pf):
            ml = p.max_loss
            total += ml
            agg["market"][p.ticker] += ml
            agg["event"][p.event_ticker or p.ticker] += ml
            agg["category"][p.category or p.desk or "OTHER"] += ml
            if p.cluster:
                agg["cluster"][p.cluster] += ml
            for t in p.teams:
                agg["team"][t] += ml
            for pl in p.players:
                agg["player"][pl] += ml
            if p.league:
                agg["league"][p.league] += ml
            if p.settlement_source:
                agg["settlement_source"][p.settlement_source] += ml
            agg["strategy"][p.strategy_id] += ml
            if p.desk in CRYPTO_MACRO_DESKS:
                cm += ml
                if p.desk == "CRYPTO":
                    agg["expiry"][p.event_ticker or p.ticker] += ml
        return {"total": total, "crypto_macro": cm, **{k: dict(v) for k, v in agg.items()}}

    def stress_losses(self, positions: Iterable[Position], spot: dict) -> dict:
        out = {}
        for name, shock in STRESS_SCENARIOS.items():
            loss = ZERO
            for p in positions:
                if p.desk not in CRYPTO_MACRO_DESKS:
                    continue
                is_crypto = p.desk == "CRYPTO"
                mv = shock["crypto"] if is_crypto else shock["equity"]
                s = spot.get(p.asset) if p.asset else None
                if s is None or p.strike is None or p.strike_direction not in ("above", "below"):
                    if mv != 0:
                        loss += p.max_loss  # unknown geometry: assume the stake is lost
                    continue
                shocked = D(str(s)) * (D("1") + mv)
                yes_wins = shocked > p.strike if p.strike_direction == "above" else shocked < p.strike
                if (p.side == "yes") != yes_wins:
                    loss += p.max_loss
            out[name] = loss
        return out

    # ---- the checks ------------------------------------------------------------------
    def evaluate(self, order: OrderIntent, market: Optional[MarketInfo], pf: PortfolioState,
                 now: Optional[float] = None) -> list[CheckResult]:
        L = self.L
        now = now if now is not None else self.clock()
        R: list[CheckResult] = []
        add = lambda code, ok, detail="": R.append(CheckResult(code, bool(ok), detail))
        nav = pf.nav if pf.nav > 0 else ZERO

        add("KILL_SWITCH", not self.kill.tripped, self.kill.reason or "armed")
        dd = (pf.peak_nav - pf.nav) / pf.peak_nav if pf.peak_nav > 0 else ZERO
        add("DRAWDOWN_KILL", dd < L.drawdown_kill_frac, f"drawdown {dd:.2%} vs kill {L.drawdown_kill_frac:.0%}")
        day_cap = pf.start_of_day_nav * L.daily_loss_frac
        add("DAILY_LOSS", -pf.day_pnl < day_cap, f"day P&L {pf.day_pnl} vs cap -{day_cap:.2f}")
        if order.source == "manual":
            add("MANUAL_DAILY_CAP", -pf.manual_day_pnl < L.manual_daily_loss_usd,
                f"manual day P&L {pf.manual_day_pnl} vs cap -{L.manual_daily_loss_usd}")
        caps = self.strategy_caps.get(order.strategy_id)
        if caps:
            sp = pf.strategy_day_pnl.get(order.strategy_id, ZERO)
            add("STRATEGY_DAILY_CAP", -sp < caps.daily_loss_usd, f"strategy day P&L {sp} vs cap -{caps.daily_loss_usd}")

        add("MARKET_OPEN", market is not None and market.is_open,
            "no market data" if market is None else f"status={market.status}")
        ranges = market.price_ranges if (market and market.price_ranges) else money.DEFAULT_RANGES
        price_ok = D("0") < order.price < D("1") and money.on_tick(order.price, ranges)
        add("PRICE_TICK", price_ok, f"price {order.price}")
        cnt_ok = isinstance(order.count, int) and order.count >= 1 and order.side in ("yes", "no") \
            and order.action in ("buy", "sell") and order.tif in ("gtc", "ioc", "fok")
        add("COUNT_VALID", cnt_ok, f"count={order.count} side={order.side} action={order.action} tif={order.tif}")
        if not (price_ok and cnt_ok):
            return R

        # fees
        fee_amt = ZERO
        try:
            ft = market.fee_type if market else "quadratic"
            fm = market.fee_multiplier if market else D("1")
            fee_amt = money.fee(order.price, order.count, fee_type=ft, multiplier=fm,
                                liquidity="maker" if order.post_only else order.expected_liquidity)
            add("FEE_KNOWN", True, f"fee {fee_amt} ({ft}, M={fm})")
        except money.FeeUnknown as e:
            add("FEE_KNOWN", False, str(e))
        inc = _order_increment(order, pf, fee_amt)
        order_loss = money.max_loss(order.side, order.action, order.price, order.count, fee_amt)

        add("MAX_ORDER_CONTRACTS", order.count <= L.max_order_contracts, f"{order.count} <= {L.max_order_contracts}")
        add("MAX_ORDER_LOSS", order_loss <= L.max_order_loss_usd, f"max loss ${order_loss} <= ${L.max_order_loss_usd}")
        if caps:
            add("STRATEGY_MAX_CONTRACTS", order.count <= caps.max_contracts, f"{order.count} <= {caps.max_contracts}")

        mid = market.mid_for(order.side) if market else None
        if mid is None:
            add("FAT_FINGER", True, "no two-sided book: check skipped")
        else:
            add("FAT_FINGER", abs(order.price - mid) <= L.fat_finger_cents,
                f"price {order.price} vs mid {mid:.4f} (max {L.fat_finger_cents})")

        ex = self.exposures(pf)
        ev = order.event_ticker or (market.event_ticker if market else None) or order.ticker
        cat = order.category or order.desk or "OTHER"

        def cap(code, current, frac_or_usd, label, usd=False):
            limit = frac_or_usd if usd else nav * frac_or_usd
            after = current + inc
            add(code, inc == 0 or after <= limit, f"{label}: ${after:.2f} after vs cap ${limit:.2f}")

        cap("PER_MARKET", ex["market"].get(order.ticker, ZERO), L.per_market_frac, "market worst case")
        cap("PER_EVENT", ex["event"].get(ev, ZERO), L.per_event_frac, "event worst case")
        cap("PER_CATEGORY", ex["category"].get(cat, ZERO), L.per_category_frac, f"category {cat}")
        if order.cluster:
            cap("CLUSTER", ex["cluster"].get(order.cluster, ZERO), L.cluster_frac, f"cluster {order.cluster}")
        for t in order.teams:
            cap("TEAM", ex["team"].get(t, ZERO), L.team_frac, f"team {t}")
        for pl in order.players:
            cap("PLAYER", ex["player"].get(pl, ZERO), L.player_frac, f"player {pl}")
        if order.league:
            cap("LEAGUE", ex["league"].get(order.league, ZERO), L.league_frac, f"league {order.league}")
        if order.settlement_source:
            cap("SETTLEMENT_SOURCE", ex["settlement_source"].get(order.settlement_source, ZERO),
                L.settlement_source_frac, f"source {order.settlement_source}")

        # bankroll at risk / cash floor
        bar_limit = nav * L.bankroll_at_risk_frac
        add("BANKROLL_AT_RISK", inc == 0 or ex["total"] + inc <= bar_limit,
            f"sum of max losses ${ex['total'] + inc:.2f} vs ${bar_limit:.2f}")
        add("CASH_FLOOR", inc == 0 or pf.cash - inc >= nav * L.min_cash_frac,
            f"cash after ${pf.cash - inc:.2f} vs floor ${nav * L.min_cash_frac:.2f}")

        # crypto / macro (§4.4)
        if (order.desk or "") in CRYPTO_MACRO_DESKS:
            if order.desk == "CRYPTO" and market and market.close_ts:
                secs = market.close_ts - now
                add("CRYPTO_WINDOW", inc == 0 or secs > L.crypto_no_entry_window_s,
                    f"{secs:.0f}s to close (no new entry inside final {L.crypto_no_entry_window_s}s)")
            cap("CRYPTO_MACRO", ex["crypto_macro"], L.crypto_macro_frac, "crypto+macro worst case")
            if order.desk == "CRYPTO":
                cap("CRYPTO_EXPIRY", ex["expiry"].get(ev, ZERO), L.crypto_per_expiry_frac, f"expiry {ev}")
            bought_side, paid = _bought(order)
            hypo = Position(ticker=order.ticker, side=bought_side, count=order.count, avg_price=paid,
                            desk=order.desk, asset=order.asset, event_ticker=ev,
                            strike=market.strike if market else None,
                            strike_direction=market.strike_direction if market else None)
            stress = self.stress_losses(self._book(pf) + ([hypo] if inc > 0 else []), pf.spot)
            worst_name, worst = max(stress.items(), key=lambda kv: kv[1])
            limit = nav * L.crypto_macro_frac
            add("CRYPTO_STRESS", inc == 0 or worst <= limit, f"worst scenario '{worst_name}' ${worst:.2f} vs ${limit:.2f}")

        if caps:
            lim = min(caps.exposure_usd, nav * L.start_exposure_frac) if nav > 0 else caps.exposure_usd
            cur = ex["strategy"].get(order.strategy_id, ZERO)
            add("STRATEGY_EXPOSURE", inc == 0 or cur + inc <= lim, f"strategy worst case ${cur + inc:.2f} vs ${lim:.2f}")
        return R

    @staticmethod
    def first_failure(results: list[CheckResult]) -> Optional[CheckResult]:
        return next((r for r in results if not r.ok), None)

    def default_caps(self) -> StrategyCaps:
        L = self.L
        return StrategyCaps(L.start_exposure_usd, L.start_max_contracts, L.start_daily_loss_usd)

    def utilization(self, pf: PortfolioState) -> dict:
        """For the RISK page."""
        L, nav = self.L, pf.nav
        ex = self.exposures(pf)
        def top(d):
            return max(d.values(), default=ZERO)
        rows = [
            ("Daily loss (fund)", -pf.day_pnl, pf.start_of_day_nav * L.daily_loss_frac),
            ("Drawdown from peak", pf.peak_nav - pf.nav, pf.peak_nav * L.drawdown_kill_frac),
            ("Manual day loss", -pf.manual_day_pnl, L.manual_daily_loss_usd),
            ("Largest market", top(ex["market"]), nav * L.per_market_frac),
            ("Largest event", top(ex["event"]), nav * L.per_event_frac),
            ("Largest category", top(ex["category"]), nav * L.per_category_frac),
            ("Largest cluster", top(ex["cluster"]), nav * L.cluster_frac),
            ("Largest team", top(ex["team"]), nav * L.team_frac),
            ("Largest player", top(ex["player"]), nav * L.player_frac),
            ("Largest league", top(ex["league"]), nav * L.league_frac),
            ("Crypto + macro", ex["crypto_macro"], nav * L.crypto_macro_frac),
            ("Largest crypto expiry", top(ex["expiry"]), nav * L.crypto_per_expiry_frac),
            ("Bankroll at risk", ex["total"], nav * L.bankroll_at_risk_frac),
            ("Largest settlement source", top(ex["settlement_source"]), nav * L.settlement_source_frac),
        ]
        stress = self.stress_losses(self._book(pf), pf.spot)
        return {
            "limits": [{"name": n, "used": str(u.quantize(D('0.01'))), "cap": str(c.quantize(D('0.01'))),
                        "pct": float(u / c * 100) if c > 0 else 0.0} for n, u, c in rows],
            "stress": {k: str(v) for k, v in stress.items()},
            "size_multiplier": str(self.size_multiplier(pf)),
            "kill": {"tripped": self.kill.tripped, "reason": self.kill.reason, "ts": self.kill.ts},
        }
