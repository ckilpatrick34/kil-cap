"""Backtest engine to the spec v4 §6 report standard.

- Point-in-time: decisions only see candles with ts <= decision time; results only after settlement;
  universe = every settled cached market (no survivorship); MSU markets dropped.
- Fills: taker fills at the first bar at or after decision + latency, only if that bar's ask <= limit;
  maker fills only on a STRICT trade-through of our price (no fills at the touch), capped at a share of
  bar volume.  Prices snapped to each market's tick grid.
- Fees: exact Kalshi formula per fill (fee_type, fee_multiplier).
- Same risk code as live: every simulated order goes through RiskEngine.evaluate (incl. MSU block).
- Walk-forward (train 120 d, test 30 d, step 30 d) on the pre-holdout period, plus an untouched final
  holdout (most recent 20%, at least 8 weeks when the data allows).
- Event-clustered bootstrap (clustered by date) for 95% CIs; Brier/log loss vs market; CLV; robustness;
  concentration; multiple testing (BH + deflated Sharpe); power check; build verdict + v4 bar.
"""
from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from ..config import RiskLimits, RiskLimitsManager
from ..core import blocklist, desks, money
from ..core.orders import MarketInfo, OrderIntent, PortfolioState, Position
from ..core.risk import RiskEngine
from ..strategies.base import Decision, Strategy, ask_for

D = Decimal
DAY = 86400.0


@dataclass
class SimConfig:
    allocation: Decimal = D("5000")      # strategy allocation / simulated NAV
    latency_s: float = 2.0               # REST latency (§6.1)
    fee_mult: Decimal = D("1")           # robustness: fees +10%, x2
    maker_fill_frac: float = 0.25        # share of through-volume we get
    size_mult: float = 1.0
    train_days: int = 120
    test_days: int = 30
    step_days: int = 30
    holdout_frac: float = 0.20
    holdout_min_days: int = 56
    bootstrap_n: int = 2000
    seed: int = 7
    min_effect_roi: float = 0.02         # power check: detect +2% ROI per event (proposed default)
    use_risk: bool = True


@dataclass
class Bet:
    ticker: str
    event: str
    day: str
    desk: str
    league: Optional[str]
    asset: Optional[str]
    side: str
    price: Decimal
    count: int
    fee: Decimal
    liquidity: str
    won: bool
    pnl: Decimal
    risk: Decimal
    q: Optional[float]
    mkt_p: float
    clv_cents: Optional[float]
    fill_ts: float
    close_ts: float
    bar_volume: int
    fold: str


# ---- fill simulation -----------------------------------------------------------------------

def _ranges(m):
    return money.parse_price_ranges(m.get("price_ranges"))


def simulate_fill(m: dict, d: Decision, cfg: SimConfig) -> Optional[tuple[float, Decimal, int, int]]:
    """Return (fill_ts, price, count, bar_volume) or None."""
    candles = m.get("candles", [])
    rng = _ranges(m)
    limit = money.snap(d.price, rng, "down") if d.side else d.price
    count = max(1, int(round(d.count * cfg.size_mult)))
    if d.liquidity == "taker":
        t0 = d.ts + cfg.latency_s
        for c in candles:
            if c["ts"] < t0 or c["ts"] > m["close_ts"]:
                continue
            ask = ask_for(c, d.side)
            if ask is None or not (D("0") < ask < D("1")):
                return None
            if ask <= limit:
                return c["ts"], money.snap(ask, rng, "up"), count, c.get("volume", 0)
            return None   # next executable bar is worse than our cap: IOC-with-cap misses
        return None
    # maker: rest from the next bar until close; fill on strict trade-through only
    for c in candles:
        if c["ts"] <= d.ts or c["ts"] > m["close_ts"]:
            continue
        lo, hi = c.get("price_low"), c.get("price_high")
        if lo is None or hi is None:
            continue
        through = (lo < limit) if d.side == "yes" else (hi > D("1") - limit)
        if through and c.get("volume", 0) > 0:
            n = min(count, int(c["volume"] * cfg.maker_fill_frac))
            if n >= 1:
                return c["ts"], limit, n, c["volume"]
    return None


def _clv(m: dict, side: str, fill_price: Decimal) -> Optional[float]:
    """Fill vs the Kalshi close: last price before close (crypto: T-5 min, outside the 60-s window)."""
    ref_t = m["close_ts"] - (300 if desks.desk_for(m.get("series_ticker"), m.get("category")) == "CRYPTO" else 0)
    last = None
    for c in m.get("candles", []):
        if c["ts"] <= ref_t and c.get("price") is not None:
            last = c["price"]
    if last is None:
        return None
    close_side = last if side == "yes" else D("1") - last
    return float((close_side - fill_price) * 100)


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


# ---- core run ------------------------------------------------------------------------------

class _SimBook:
    """Minimal portfolio for running live risk checks inside the backtest."""

    def __init__(self, nav: Decimal):
        self.nav = nav
        self.peak = nav
        self.open: list[tuple[float, Position, Decimal]] = []  # (settle_ts, position, pnl)
        self.day = None
        self.sod = nav
        self.day_pnl = D("0")

    def advance(self, t: float):
        keep = []
        for st, pos, pnl in self.open:
            if st <= t:
                self.nav += pnl
                self.day_pnl += pnl
                self.peak = max(self.peak, self.nav)
            else:
                keep.append((st, pos, pnl))
        self.open = keep
        d = _day(t)
        if d != self.day:
            self.day, self.sod, self.day_pnl = d, self.nav, D("0")

    def state(self) -> PortfolioState:
        locked = sum((p.max_loss for _, p, _ in self.open), D("0"))
        return PortfolioState(nav=self.nav, cash=self.nav - locked, start_of_day_nav=self.sod,
                              peak_nav=self.peak, day_pnl=self.day_pnl, positions=[p for _, p, _ in self.open])


def run_window(strategy: Strategy, markets: list[dict], cfg: SimConfig, fold: str, book: _SimBook,
               risk: Optional[RiskEngine]) -> tuple[list[Bet], int]:
    bets, rejected = [], 0
    pending = []
    for m in markets:
        if blocklist.check_market(m).blocked or not strategy.accepts(m):
            continue
        for d in strategy.decisions(m):
            pending.append((d.ts, m, d))
    pending.sort(key=lambda x: x[0])
    for ts, m, d in pending:
        book.advance(ts)
        f = simulate_fill(m, d, cfg)
        if not f:
            continue
        fill_ts, px, n, vol = f
        t = desks.tags(m.get("series_ticker"), m.get("category"))
        try:
            fee = money.fee(px, n, fee_type=m.get("fee_type", "quadratic"),
                            multiplier=D(str(m.get("fee_multiplier", 1))), liquidity=d.liquidity) * cfg.fee_mult
        except (money.FeeUnknown, ValueError):
            continue
        if risk is not None:
            c = next((c for c in reversed(m["candles"]) if c["ts"] <= fill_ts), {})
            mi = MarketInfo(ticker=m["ticker"], status="open", event_ticker=m.get("event_ticker"),
                            series_ticker=m.get("series_ticker"), category=m.get("category"), title=m.get("title", ""),
                            price_ranges=_ranges(m), yes_bid=c.get("yes_bid"), yes_ask=c.get("yes_ask"),
                            close_ts=m["close_ts"], fee_type=m.get("fee_type", "quadratic"),
                            fee_multiplier=D(str(m.get("fee_multiplier", 1))), raw=m)
            oi = OrderIntent(ticker=m["ticker"], side=d.side, action="buy", price=px, count=n,
                             strategy_id=strategy.id, post_only=d.liquidity == "maker",
                             event_ticker=m.get("event_ticker"), series_ticker=m.get("series_ticker"),
                             expected_liquidity=d.liquidity, **t)
            res = risk.evaluate(oi, mi, book.state(), now=fill_ts)
            ok = all(r.ok for r in res if r.code != "KILL_SWITCH") and blocklist.check_market(m).blocked is False
            if not ok:
                rejected += 1
                continue
        won = m["result"] == d.side
        cost = px * n
        pnl = (D(n) - cost - fee) if won else (-cost - fee)
        mkt_p = None
        c_dec = next((c for c in reversed(m["candles"]) if c["ts"] <= d.ts), None)
        if c_dec and c_dec.get("yes_bid") is not None and c_dec.get("yes_ask") is not None:
            mid = (c_dec["yes_bid"] + c_dec["yes_ask"]) / 2
            mkt_p = float(mid if d.side == "yes" else 1 - mid)
        else:
            mkt_p = float(px)
        b = Bet(ticker=m["ticker"], event=m.get("event_ticker") or m["ticker"], day=_day(m["close_ts"]),
                desk=t["desk"], league=t["league"], asset=t["asset"], side=d.side, price=px, count=n, fee=fee,
                liquidity=d.liquidity, won=won, pnl=pnl, risk=cost + fee,
                q=None if d.q is None else float(d.q), mkt_p=mkt_p, clv_cents=_clv(m, d.side, px),
                fill_ts=fill_ts, close_ts=m["close_ts"], bar_volume=vol, fold=fold)
        bets.append(b)
        pos = Position(ticker=m["ticker"], side=d.side, count=n, avg_price=px, strategy_id=strategy.id,
                       event_ticker=m.get("event_ticker"), desk=t["desk"], category=m.get("category") or t["desk"],
                       league=t["league"], asset=t["asset"])
        book.open.append((m["close_ts"], pos, pnl))
    return bets, rejected


def split_folds(markets: list[dict], cfg: SimConfig):
    """Return (walk_forward_folds, holdout_train, holdout_test).  Each fold = (name, train, test)."""
    if not markets:
        return [], [], []
    t0, t1 = markets[0]["close_ts"], markets[-1]["close_ts"]
    span = t1 - t0
    hold_len = max(span * cfg.holdout_frac, min(cfg.holdout_min_days * DAY, span * 0.5))
    hold_start = t1 - hold_len
    pre = [m for m in markets if m["close_ts"] < hold_start]
    hold = [m for m in markets if m["close_ts"] >= hold_start]
    folds = []
    start = t0 + cfg.train_days * DAY
    i = 0
    while start < hold_start:
        end = min(start + cfg.test_days * DAY, hold_start)
        train = [m for m in pre if start - cfg.train_days * DAY <= m["close_ts"] < start]
        test = [m for m in pre if start <= m["close_ts"] < end]
        if test:
            folds.append((f"wf{i}", train, test))
            i += 1
        start += cfg.step_days * DAY
    return folds, pre, hold


# ---- statistics ------------------------------------------------------------------------------

def _roi(bets):
    r = sum((b.risk for b in bets), D("0"))
    return float(sum((b.pnl for b in bets), D("0")) / r) if r > 0 else 0.0


def cluster_bootstrap(bets: list[Bet], fn, n=2000, seed=7):
    by_day = defaultdict(list)
    for b in bets:
        by_day[b.day].append(b)
    days = list(by_day)
    if len(days) < 2:
        return None, None, None
    rnd = random.Random(seed)
    vals = []
    for _ in range(n):
        sample = []
        for _ in days:
            sample.extend(by_day[rnd.choice(days)])
        v = fn(sample)
        if v is not None:
            vals.append(v)
    if not vals:
        return None, None, None
    vals.sort()
    lo, hi = vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))]
    p_le0 = sum(1 for v in vals if v <= 0) / len(vals)
    return lo, hi, p_le0


def brier_logloss(bets):
    mb = [b for b in bets if b.q is not None]
    if not mb:
        return None
    eps = 1e-6
    def bl(p, y):
        p = min(max(p, eps), 1 - eps)
        return (p - y) ** 2, -(y * math.log(p) + (1 - y) * math.log(1 - p))
    mod = [bl(b.q, 1.0 if b.won else 0.0) for b in mb]
    mkt = [bl(b.mkt_p, 1.0 if b.won else 0.0) for b in mb]
    return {"n": len(mb), "model_brier": statistics.fmean(x[0] for x in mod),
            "market_brier": statistics.fmean(x[0] for x in mkt),
            "model_logloss": statistics.fmean(x[1] for x in mod),
            "market_logloss": statistics.fmean(x[1] for x in mkt)}


def drawdown(bets, allocation: Decimal):
    eq, peak, mdd = D("0"), D("0"), D("0")
    curve = []
    uw_start, longest_uw = None, 0.0
    streak = longest_streak = 0
    for b in sorted(bets, key=lambda x: x.close_ts):
        eq += b.pnl
        if eq >= peak:
            peak = eq
            if uw_start is not None:
                longest_uw = max(longest_uw, b.close_ts - uw_start)
                uw_start = None
        elif uw_start is None:
            uw_start = b.close_ts
        mdd = max(mdd, peak - eq)
        streak = 0 if b.pnl > 0 else streak + 1
        longest_streak = max(longest_streak, streak)
        curve.append({"t": b.close_ts, "equity": float(eq), "dd": float(eq - peak), "fold": b.fold})
    if uw_start is not None and bets:
        longest_uw = max(longest_uw, max(b.close_ts for b in bets) - uw_start)
    return {"max_dd_usd": float(mdd), "max_dd_pct_alloc": float(mdd / allocation * 100) if allocation else None,
            "longest_under_water_days": round(longest_uw / DAY, 1), "longest_losing_streak": longest_streak}, curve


def deflated_sharpe(event_returns: list[float], n_trials: int) -> Optional[float]:
    """Bailey & Lopez de Prado deflated Sharpe ratio (probability the true SR > 0 after N trials)."""
    n = len(event_returns)
    if n < 10:
        return None
    mu = statistics.fmean(event_returns)
    sd = statistics.pstdev(event_returns)
    if sd == 0:
        return None
    sr = mu / sd
    m3 = statistics.fmean(((x - mu) / sd) ** 3 for x in event_returns)
    m4 = statistics.fmean(((x - mu) / sd) ** 4 for x in event_returns)
    N = max(1, n_trials)
    emc = 0.5772156649
    nd = statistics.NormalDist()
    sr0 = 0.0 if N == 1 else math.sqrt(1.0 / n) * ((1 - emc) * nd.inv_cdf(1 - 1.0 / N) + emc * nd.inv_cdf(1 - 1.0 / (N * math.e)))
    denom = math.sqrt(max(1e-12, 1 - m3 * sr + (m4 - 1) / 4 * sr * sr))
    return nd.cdf((sr - sr0) * math.sqrt(n - 1) / denom)


def bh_adjust(pvals: list[float]) -> list[float]:
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, pvals[i] * m / rank)
        adj[i] = prev
    return adj


def events_needed(event_returns: list[float], effect: float) -> Optional[int]:
    if len(event_returns) < 5:
        return None
    sd = statistics.pstdev(event_returns) or 1.0
    z = 1.645 + 0.8416  # one-sided alpha 0.05, power 0.80
    return int(math.ceil((z * sd / effect) ** 2))


def _event_returns(bets):
    by_ev = defaultdict(lambda: [D("0"), D("0")])
    for b in bets:
        by_ev[b.event][0] += b.pnl
        by_ev[b.event][1] += b.risk
    return {e: float(p / r) if r > 0 else 0.0 for e, (p, r) in by_ev.items()}, by_ev


# ---- report -----------------------------------------------------------------------------------

def summarize(bets: list[Bet], cfg: SimConfig) -> dict:
    if not bets:
        return {"bets": 0, "events": 0}
    pnl = sum((b.pnl for b in bets), D("0"))
    risk = sum((b.risk for b in bets), D("0"))
    traded = sum((b.price * b.count for b in bets), D("0"))
    wins = [b for b in bets if b.pnl > 0]
    losses = [b for b in bets if b.pnl <= 0]
    lo, hi, p_le0 = cluster_bootstrap(bets, _roi, cfg.bootstrap_n, cfg.seed)
    clv = [b.clv_cents for b in bets if b.clv_cents is not None]
    clv_lo, clv_hi, _ = cluster_bootstrap([b for b in bets if b.clv_cents is not None],
                                          lambda s: statistics.fmean(x.clv_cents for x in s) if s else None,
                                          cfg.bootstrap_n, cfg.seed)
    dd, curve = drawdown(bets, cfg.allocation)
    ev_ret, by_ev = _event_returns(bets)
    top5 = sorted(by_ev.items(), key=lambda kv: kv[1][0], reverse=True)[:5]
    top5_share = float(sum(v[0] for _, v in top5) / pnl) if pnl > 0 else None
    return {
        "bets": len(bets), "events": len(by_ev),
        "net_pnl": float(pnl), "capital_at_risk": float(risk),
        "roi": float(pnl / risk) if risk else 0.0, "net_yield": float(pnl / traded) if traded else 0.0,
        "roi_ci95": [lo, hi], "p_value_roi_le_0": p_le0,
        "hit_rate": len(wins) / len(bets),
        "avg_win": float(statistics.fmean(float(b.pnl) for b in wins)) if wins else 0.0,
        "avg_loss": float(statistics.fmean(float(b.pnl) for b in losses)) if losses else 0.0,
        "fees_paid": float(sum((b.fee for b in bets), D("0"))),
        "clv_cents_mean": statistics.fmean(clv) if clv else None, "clv_ci95": [clv_lo, clv_hi],
        "brier": brier_logloss(bets), **dd,
        "top5_event_share_of_pnl": top5_share,
        "max_single_event_share": (float(max(v[0] for v in by_ev.values()) / pnl) if pnl > 0 else None),
        "median_bar_volume": statistics.median([b.bar_volume for b in bets]),
        "median_size": statistics.median([b.count for b in bets]),
        "_curve": curve, "_event_returns": list(ev_ret.values()),
    }


def _by(bets, key):
    g = defaultdict(list)
    for b in bets:
        g[getattr(b, key) or "-"].append(b)
    return {k: {"bets": len(v), "roi": _roi(v), "pnl": float(sum((x.pnl for x in v), D('0')))} for k, v in g.items()}


def run_backtest(strategy: Strategy, markets: list[dict], cfg: SimConfig | None = None,
                 limits: RiskLimits | None = None, n_variants_tried: int = 1, _robust=True) -> dict:
    cfg = cfg or SimConfig()
    markets = [m for m in markets if not blocklist.check_market(m).blocked]
    markets.sort(key=lambda m: m["close_ts"])
    universe = [m for m in markets if strategy.accepts(m)]
    base = {"strategy_id": strategy.id, "info": strategy.info(), "universe_markets": len(universe),
            "config": {k: str(v) for k, v in cfg.__dict__.items()}}
    if strategy.needs_paid_data and not any(strategy.decisions(m) for m in universe[:200]):
        return {**base, "verdict": "NO DATA", "notes": [f"Needs {strategy.needs_paid_data}."]}
    if not universe:
        return {**base, "verdict": "NO DATA", "notes": ["No settled markets in the cache for this strategy. "
                                                        "Run: python -m kil_capital.backtest.fetch"]}
    folds, pre, hold = split_folds(universe, cfg)

    def mk_risk():
        return RiskEngine(RiskLimitsManager(limits or RiskLimits())) if cfg.use_risk else None

    book = _SimBook(cfg.allocation)
    risk = mk_risk()
    wf_bets, fold_stats, rejected = [], [], 0
    for name, train, test in folds:
        strategy.fit(train)
        b, r = run_window(strategy, test, cfg, name, book, risk)
        rejected += r
        wf_bets.extend(b)
        fold_stats.append({"fold": name, "bets": len(b), "roi": _roi(b) if b else None,
                           "train_markets": len(train), "test_markets": len(test)})
    strategy.fit(pre)
    hold_bets, r = run_window(strategy, hold, cfg, "holdout", book, risk)
    rejected += r
    oos = wf_bets + hold_bets
    if not oos:
        return {**base, "verdict": "NO TRADES", "folds": fold_stats, "risk_rejections": rejected,
                "notes": ["Strategy produced no fills out of sample."]}

    s_oos = summarize(oos, cfg)
    s_hold = summarize(hold_bets, cfg) if hold_bets else {"bets": 0}
    s_wf = summarize(wf_bets, cfg) if wf_bets else {"bets": 0}
    curve = s_oos.pop("_curve")
    ev_returns = s_oos.pop("_event_returns")
    for s in (s_hold, s_wf):
        s.pop("_curve", None)
        s.pop("_event_returns", None)

    # robustness
    robust = {}
    if _robust:
        def rerun(**kw):
            c2 = replace(cfg, bootstrap_n=200, **kw)
            rep = run_backtest(strategy, markets, c2, limits, n_variants_tried, _robust=False)
            return rep.get("oos", {}).get("roi") if isinstance(rep.get("oos"), dict) else None
        robust = {"fees +10%": rerun(fee_mult=D("1.1")), "fees x2": rerun(fee_mult=D("2")),
                  "latency 2x": rerun(latency_s=cfg.latency_s * 2), "latency 5x": rerun(latency_s=cfg.latency_s * 5),
                  "maker fills 10%": rerun(maker_fill_frac=0.10), "maker fills 25%": rerun(maker_fill_frac=0.25),
                  "maker fills 50%": rerun(maker_fill_frac=0.50),
                  "size 0.5x": rerun(size_mult=0.5), "size 2x": rerun(size_mult=2.0)}
        ev_sorted = sorted(_event_returns(oos)[1].items(), key=lambda kv: kv[1][0], reverse=True)
        top5 = {e for e, _ in ev_sorted[:5]}
        robust["drop top 5 events"] = _roi([b for b in oos if b.event not in top5]) if len(ev_sorted) > 5 else None
        hb = sorted(hold_bets, key=lambda b: b.close_ts)
        half = len(hb) // 2
        robust["holdout 1st half"] = _roi(hb[:half]) if half else None
        robust["holdout 2nd half"] = _roi(hb[half:]) if half else None

    # multiple testing / power
    need = events_needed(ev_returns, cfg.min_effect_roi)
    dsr = deflated_sharpe(ev_returns, n_variants_tried)
    p = s_oos.get("p_value_roi_le_0")
    p_bh = min(1.0, p * n_variants_tried) if p is not None else None  # conservative single-strategy BH bound
    signs = [f["roi"] > 0 for f in fold_stats if f["roi"] is not None]
    same_sign = (sum(signs) / len(signs)) if signs else None

    rep = {**base, "oos": s_oos, "walk_forward": s_wf, "holdout": s_hold, "folds": fold_stats,
           "robustness": robust, "breakdown": {"desk": _by(oos, "desk"), "league": _by(oos, "league"),
                                               "asset": _by(oos, "asset"), "liquidity": _by(oos, "liquidity")},
           "equity_curve": curve, "holdout_start": hold[0]["close_ts"] if hold else None,
           "multiple_testing": {"variants_tried": n_variants_tried, "p_value": p, "p_bh_adjusted": p_bh,
                                "deflated_sharpe_prob": dsr},
           "power": {"events_needed_80pct": need, "events_available": s_oos["events"],
                     "untestable": need is not None and s_oos["events"] < need},
           "fold_same_sign_share": same_sign, "risk_rejections": rejected}
    rep["build_verdict"], rep["notes"] = build_verdict(strategy, rep)
    rep["v4_bar"] = v4_bar(strategy, rep, cfg)
    rep["verdict"] = rep["build_verdict"]
    return rep


def build_verdict(strategy: Strategy, rep: dict):
    o = rep["oos"]
    notes = []
    lo, hi = o["roi_ci95"]
    br = o.get("brier")
    model_worse = bool(strategy.is_model and br and br["model_brier"] > br["market_brier"])
    if model_worse:
        notes.append(f"Model Brier {br['model_brier']:.4f} is worse than market {br['market_brier']:.4f}.")
    if rep["power"]["untestable"]:
        notes.append(f"Untestable at 80% power: needs ~{rep['power']['events_needed_80pct']} events, have {o['events']}.")
    if o["events"] < 100:
        notes.append(f"Only {o['events']} OOS events: far too few to judge.")
    if hi is not None and hi < 0:
        return "FAIL", notes + ["95% CI on ROI is entirely below 0."]
    if model_worse and o["roi"] <= 0:
        return "FAIL", notes
    if o["events"] >= 100 and lo is not None and lo > 0 and not model_worse:
        return "PASS", notes
    return "INCONCLUSIVE", notes


def v4_bar(strategy: Strategy, rep: dict, cfg: SimConfig) -> list[dict]:
    """The §6.3 suggested go-live bar, line by line (guidance, NOT a gate)."""
    o, h, rb = rep["oos"], rep.get("holdout", {}), rep.get("robustness", {})
    br = o.get("brier")
    def row(n, ok, detail):
        return {"item": n, "ok": ok, "detail": detail}
    lo = o["roi_ci95"][0]
    rows = []
    if strategy.structural:
        rows.append(row("Structural: positive net on every instance, zero rules-mismatch losses",
                        o["avg_loss"] >= 0 and o["bets"] > 0, "300-event rule waived for S1/CR1"))
    rows.append(row("1. OOS ROI after fees > 0 with 95% CI lower bound > 0", o["roi"] > 0 and lo is not None and lo > 0,
                    f"ROI {o['roi']:.2%}, CI low {lo if lo is None else f'{lo:.2%}'}"))
    f10, l2 = rb.get("fees +10%"), rb.get("latency 2x")
    rows.append(row("2. Holds at fees +10% and 2x latency", f10 is not None and l2 is not None and f10 > 0 and l2 > 0,
                    f"fees+10% {f10}, latency2x {l2}"))
    if not strategy.structural:
        rows.append(row("3. >= 300 independent OOS events (niche >= 150, weak)", o["events"] >= 300,
                        f"{o['events']} events" + (" (weak niche pass)" if 150 <= o["events"] < 300 else "")))
    cl = o.get("clv_ci95", [None, None])[0]
    rows.append(row("4. CLV lower bound > 0", cl is not None and cl > 0, f"CLV mean {o.get('clv_cents_mean')}c, LCB {cl}"))
    if strategy.is_model:
        ok = bool(br and br["model_brier"] <= br["market_brier"] and br["model_logloss"] <= br["market_logloss"])
        rows.append(row("5. Brier and log loss no worse than market", ok, str(br)))
    ss = rep.get("fold_same_sign_share")
    rows.append(row("6. Same sign in >= 2/3 of walk-forward folds", ss is not None and ss >= 2 / 3, f"{ss}"))
    dd = o.get("max_dd_pct_alloc")
    ms = o.get("max_single_event_share")
    rows.append(row("7. Max DD < 20% of allocation and no event > 10% of P&L",
                    dd is not None and dd < 20 and (ms is None or ms <= 0.10), f"DD {dd}%, top event {ms}"))
    mt = rep["multiple_testing"]
    rows.append(row("8. BH-adjusted p <= 0.10 and deflated Sharpe > 0",
                    mt["p_bh_adjusted"] is not None and mt["p_bh_adjusted"] <= 0.10 and (mt["deflated_sharpe_prob"] or 0) > 0.5,
                    f"p_BH {mt['p_bh_adjusted']}, DSR prob {mt['deflated_sharpe_prob']}"))
    rows.append(row("9. Capacity >= intended starting size", o["median_bar_volume"] >= o["median_size"],
                    f"median bar volume {o['median_bar_volume']} vs size {o['median_size']}"))
    return rows
