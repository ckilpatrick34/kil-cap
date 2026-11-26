"""Terminal: wires every component together and runs the background loops (spec v4 §8)."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from ..config import SETTINGS, RiskLimits, RiskLimitsManager, Settings, ROOT
from ..core import blocklist, desks, money
from ..core.ledger import Ledger
from ..core.paper import PaperBook
from ..crypto.desk import CryptoDesk
from ..sports import learn, segments
from ..sports.slate import Slate
from ..core.orders import MarketInfo, OrderIntent, PortfolioState, Position
from ..core.risk import RiskEngine
from ..strategies.registry import IDEAS, Registry
from ..venue.public import PublicClient, _dollars, market_info

log = logging.getLogger("kil.terminal")
D = Decimal


def _num(d: dict, key: str) -> Optional[Decimal]:
    return _dollars(d, key)


class Terminal:
    def __init__(self, settings: Settings = SETTINGS, *, public: PublicClient | None = None,
                 start_loops: bool = True, ledger_path: str | None = None):
        self.s = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(ledger_path or settings.db_path)
        self.registry = Registry(settings.mlb_model_dir)
        self.limits = RiskLimitsManager(RiskLimits(), audit=self.ledger.audit)
        self.risk = RiskEngine(self.limits, on_auto_kill=self._on_auto_kill)
        self.public = public or PublicClient(settings.kalshi_base_url, settings.public_req_per_sec)
        # RECOMMEND-ONLY: no Kalshi account connection, no keys, no order placement of any kind.
        self.venue = None
        self.mode = "RECOMMEND-ONLY"
        self.tz = ZoneInfo(settings.timezone)
        self._pf_cache: tuple[float, PortfolioState] | None = None
        self._scan_cache: dict = {}
        self._signals_cache: dict = defaultdict(list)
        self._fee_types: dict = {}
        self._stop = threading.Event()
        self.paper = PaperBook(settings.data_dir / "paper.json")
        self.slate = Slate(self.public, settings.data_dir, settings.timezone)
        self.crypto = CryptoDesk(self.public, settings.data_dir)
        self.last_scan_ts: float | None = None
        self.started = time.time()
        self.ledger.audit("terminal.start", "system", {"mode": self.mode}, "ok")
        if start_loops:
            threading.Thread(target=self._loop, name="kil-loop", daemon=True).start()
            threading.Thread(target=self._model_loop, name="kil-models", daemon=True).start()

    # ---- providers ---------------------------------------------------------------------
    def market_info(self, ticker: str) -> MarketInfo:
        return self.public.market_info(ticker)

    def _assumed_nav(self) -> Decimal:
        return D(os.environ.get("KIL_RESEARCH_NAV", "5000"))

    def portfolio(self, fresh: bool = False) -> PortfolioState:
        if self._pf_cache and not fresh and time.time() - self._pf_cache[0] < 5:
            return self._pf_cache[1]
        pf = self._build_portfolio()
        self._pf_cache = (time.time(), pf)
        return pf

    def _today(self) -> str:
        return datetime.now(self.tz).strftime("%Y-%m-%d")

    def _day_start_ts(self) -> float:
        n = datetime.now(self.tz)
        return n.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def _build_portfolio(self) -> PortfolioState:
        positions: list[Position] = []
        if self.venue is None:
            nav = cash = self._assumed_nav()
        else:
            try:
                bal = self.venue.balance()
                cash = _num(bal, "balance") or D("0")
                pv = _num(bal, "portfolio_value")
                raw = self.venue.positions(limit=1000).get("market_positions", [])
            except Exception as e:
                log.warning("portfolio sync failed: %s", e)
                self.risk.observe_venue_error()
                cash, pv, raw = D("0"), None, []
            for p in raw:
                qty = int(float(p.get("position_fp") or p.get("position") or 0))
                if qty == 0:
                    continue
                exposure = _num(p, "market_exposure") or D("0")
                side = "yes" if qty > 0 else "no"
                n = abs(qty)
                t = p.get("ticker", "")
                tags = desks.tags(desks.series_of(t))
                src = self._source_for(t)
                positions.append(Position(ticker=t, side=side, count=n,
                                          avg_price=(exposure / n) if n else D("0"),
                                          strategy_id=src[0], source=src[1],
                                          event_ticker=desks.event_of(t), series_ticker=desks.series_of(t),
                                          desk=tags["desk"], category=tags["category"], league=tags["league"],
                                          asset=tags["asset"],
                                          cluster=f"crypto:{desks.event_of(t)}" if tags["desk"] == "CRYPTO" else None))
            nav = cash + (pv if pv is not None else sum((p.max_loss for p in positions), D("0")))
        start, peak = self.ledger.nav_mark(self._today(), nav) if self.venue else (nav, nav)
        resting = []
        for o in self.ledger.orders():
            if o["status"] in ("resting", "sending", "open", "pending"):
                side, paid = money.cost_basis(o["side"], o["action"], o["price"], o["count"])
                tg = desks.tags(o.get("series_ticker"), o.get("category"))
                resting.append(Position(ticker=o["ticker"], side=side, count=int(o["count"]) - int(o["filled"] or 0),
                                        avg_price=paid, strategy_id=o["strategy_id"], source=o["source"],
                                        event_ticker=o["event_ticker"], desk=o["desk"], category=o["category"],
                                        league=o.get("league") or tg["league"], asset=o.get("asset") or tg["asset"]))
        manual, per_strat = self._day_pnl_by_source()
        return PortfolioState(nav=nav, cash=cash, start_of_day_nav=start, peak_nav=peak, day_pnl=nav - start,
                              manual_day_pnl=manual, strategy_day_pnl=per_strat, positions=positions, resting=resting)

    def _source_for(self, ticker: str):
        for f in self.ledger.fills(limit=2000):
            if f["ticker"] == ticker:
                return f["strategy_id"] or "external", f["source"] or "external"
        return "external", "external"

    def _day_pnl_by_source(self):
        """Mark today's fills to the current mid: manual and per-strategy day P&L (for the caps)."""
        since = self._day_start_ts()
        manual, per = D("0"), defaultdict(lambda: D("0"))
        for f in self.ledger.fills(limit=5000, since=since):
            try:
                mi = self.public.market_info(f["ticker"])
                mark = mi.mid_for(f["side"])
            except Exception:
                mark = None
            px, n = D(f["price"]), int(f["count"])
            fee = D(f["fee"] or "0")
            if mark is None:
                pnl = -fee
            else:
                sgn = 1 if f["action"] == "buy" else -1
                pnl = sgn * (mark - px) * n - fee
            if f["source"] == "manual":
                manual += pnl
            per[f["strategy_id"]] += pnl
        return manual, dict(per)

    # ---- kill ----------------------------------------------------------------------------
    def _on_auto_kill(self, reason: str):
        self.ledger.audit("kill.auto", "system", {"reason": reason}, "tripped")

    # ---- scanner ---------------------------------------------------------------------------
    def scan_markets(self, max_pages: int = 5) -> list[dict]:
        hit = self._scan_cache.get("all")
        if hit and time.time() - hit[0] < 20:
            return hit[1]
        out, cursor = [], None
        for _ in range(max_pages):
            ms, cursor = self.public.markets(status="open", limit=1000, cursor=cursor)
            out.extend(ms)
            if not cursor:
                break
        for m in out:
            st = m.get("series_ticker") or desks.series_of(m.get("event_ticker", ""))
            m["_tags"] = desks.tags(st, m.get("category"))
        self._scan_cache["all"] = (time.time(), out)
        self._by_ticker = {m.get("ticker"): m for m in out}
        return out

    def run_signals(self) -> dict:
        """Record every signal as a recommendation.  Nothing is ever sent to Kalshi."""
        markets = self.scan_markets()
        pf = self.portfolio()
        mult = self.risk.size_multiplier(pf)
        summary = {}
        for s in self.registry.bots():
            try:
                sigs = s.scan(markets, time.time())
            except Exception as e:
                log.warning("scan %s failed: %s", s.id, e)
                continue
            self._signals_cache[s.id] = [{"ticker": x.ticker, "side": x.side, "price": str(x.price),
                                          "fair": None if x.fair is None else str(x.fair),
                                          "edge": None if x.edge is None else str(x.edge), "reason": x.reason,
                                          "title": x.market.get("title", ""),
                                          "sub_title": x.market.get("yes_sub_title") or "",
                                          "event_ticker": x.market.get("event_ticker"),
                                          "close_time": x.market.get("close_time"),
                                          "ts": time.time()} for x in sigs][:200]
            for x in sigs[:50]:
                self.ledger.record_signal(s.id, x.ticker, x.side, x.price, x.fair, x.features,
                                          desks.desk_for(x.market.get("series_ticker"), x.market.get("category")))
            summary[s.id] = len(sigs)
        self.last_scan_ts = time.time()
        self.paper_tick()
        return summary

    # ---- trade ideas, live quotes, paper book --------------------------------------------------
    def quote(self, ticker: str) -> tuple:
        """(yes_bid, yes_ask) from the last market scan, falling back to a direct read."""
        m = getattr(self, "_by_ticker", {}).get(ticker)
        if m is None:
            try:
                m = self.public.market(ticker)
            except Exception:
                return None, None
        return _num(m, "yes_bid"), _num(m, "yes_ask")

    def opportunities(self, limit: int = 60) -> list[dict]:
        """Every bot signal, best edge first, with the market's current price and a paper size."""
        names = {s.id: s.name for s in self.registry.all()}
        verdicts = {s.id: (self.report(s.id) or {}).get("verdict", "NO REPORT") for s in self.registry.all()}
        best: dict[tuple, dict] = {}
        for sid, rows in self._signals_cache.items():
            for r in rows:
                if blocklist.is_blocked({"ticker": r["ticker"], "title": r.get("title", "")}):
                    continue
                o = {**r, "strategy_id": sid, "strategy": names.get(sid, sid), "verdict": verdicts.get(sid)}
                k = (r["ticker"], r["side"])
                e = D(o["edge"]) if o.get("edge") else D("-1")
                if k not in best or e > (D(best[k]["edge"]) if best[k].get("edge") else D("-1")):
                    best[k] = o
        out = sorted(best.values(), key=lambda o: D(o["edge"]) if o.get("edge") else D("-1"), reverse=True)
        a = self.paper.auto
        for o in out:
            px = D(o["price"])
            o["paper_count"] = max(1, int(D(a.max_trade_usd) / (px + D("0.02")))) if D("0") < px < D("1") else 0
            o["held"] = o["ticker"] in self.paper.positions
            m = getattr(self, "_by_ticker", {}).get(o["ticker"]) or {}
            yb, ya = _num(m, "yes_bid"), _num(m, "yes_ask")
            o["yes_bid"], o["yes_ask"] = (None if yb is None else str(yb)), (None if ya is None else str(ya))
            o["volume"] = m.get("volume_24h") or m.get("volume")
        return out[:limit]

    def paper_tick(self):
        """Settle finished paper positions, then let the autopilot act on fresh opportunities."""
        for t in list(self.paper.positions):
            try:
                m = self.public.market(t)
            except Exception:
                continue
            res = (m.get("result") or "").lower()
            if m.get("status") in ("settled", "finalized", "determined") and res in ("yes", "no"):
                row = self.paper.settle(t, res)
                if row:
                    self.paper.note(f"Settled {row['title'] or t}: {res.upper()} won, P&L ${D(row['pnl']):.2f}",
                                    ticker=t)
        if self.paper.auto.enabled:
            self.paper.autopilot_step(self.trade_signals())

    def _sizing(self):
        a = self.paper.auto
        return float(a.min_edge), float(self.paper.summary(self.quote)["equity"]), float(a.max_trade_usd)

    def refresh_slate(self):
        e, eq, mt = self._sizing()
        return self.slate.refresh(min_edge=e, equity=eq, max_trade=mt)

    def refresh_crypto(self):
        e, eq, mt = self._sizing()
        return self.crypto.refresh(min_edge=e, equity=eq, max_trade=mt)

    def trade_signals(self) -> list[dict]:
        """What the autopilot may act on: game-model picks and crypto-vol picks, best first (blocklist applied)."""
        sigs = list(self.slate.snapshot().get("signals", [])) + list(self.crypto.snapshot().get("signals", []))
        return [s for s in sigs if not blocklist.is_blocked({"ticker": s["ticker"], "title": s.get("title", "")})]

    def learn_nightly(self) -> dict:
        """Retrain on settled games (promote only on unseen-game wins), then rebuild the segment table from
        Big Vin's graded history (data/bigvin_picks.json, written by research/bigvin.py) plus our own picks."""
        today = datetime.now(self.tz).date()
        res = learn.nightly(self.slate.espn, self.s.data_dir, today, self.slate.leagues)
        picks = [{"league": r["league"], "kind": r["kind"], "edge": r["edge"], "price": r["price"],
                  "won": r["result"] == "W", "ts": r["logged"]}
                 for r in self.slate.track.rows.values() if r["result"] is not None]
        try:
            picks += json.loads((self.s.data_dir / "bigvin_picks.json").read_text())
        except (OSError, ValueError):
            pass
        table = segments.build_table(picks)
        (self.s.data_dir / "segments.json").write_text(json.dumps(table, indent=1))
        self.slate._ratings.clear()                      # pick up any promoted settings on the next refresh
        self.ledger.audit("learn.nightly", "system",
                          {"promoted": [r["league"] for r in res if r.get("promoted")], "segments": len(table)}, "ok")
        return {"leagues": res, "segments": len(table)}

    def _learn_safe(self):
        try:
            self.learn_nightly()
        except Exception as e:  # never let a bad night kill the model loop
            log.warning("nightly learn error: %s", e)

    def learn_status(self) -> dict:
        d = self.s.data_dir
        log_ = learn.load(d / "learn_log.json")
        return {"params": learn.load(d / "model_params.json"), "log": (log_ if isinstance(log_, list) else [])[-20:],
                "segments": segments.load_table(d / "segments.json"),
                "deep": {k: {mk: {"promoted": v["promoted"], "market_rmse_late": v["market_rmse_late"],
                                  "models": {n: m["unseen_window"] for n, m in v["models"].items()}}
                             for mk, v in r.get("markets", {}).items()}
                         for k, r in learn.load(d / "deep_models.json").items()}}

    def _model_loop(self):
        """Slow external data (ESPN, weather, candles) lives on its own thread so it never stalls fills sync."""
        last_slate = last_crypto = 0.0
        learned_on = None
        while not self._stop.is_set():
            now = time.time()
            local = datetime.now(self.tz)
            if local.hour >= 4 and learned_on != local.date():      # nightly, after the late games settle
                learned_on = local.date()
                threading.Thread(target=self._learn_safe, name="kil-learn", daemon=True).start()
            for name, last, every, fn in (("slate", last_slate, 300, self.refresh_slate),
                                          ("crypto", last_crypto, 120, self.refresh_crypto)):
                if now - last > every:
                    try:
                        fn()
                    except Exception as e:
                        log.warning("%s refresh error: %s", name, e)
                    if name == "slate":
                        last_slate = now
                    else:
                        last_crypto = now
            self._stop.wait(10)

    def paper_summary(self) -> dict:
        d = self.paper.summary(self.quote)
        d["last_scan_ts"] = self.last_scan_ts
        clvs = []
        for p in d.get("positions", []):
            c = self.slate.clv_for(p["ticker"], p["side"], float(p["avg_price"]))
            p["clv"] = c
            if c is not None:
                clvs.append(c)
        d["avg_clv"] = round(sum(clvs) / len(clvs), 3) if clvs else None
        return d

    def signals(self, sid: str):
        return self._signals_cache.get(sid, [])

    # ---- fills sync / integrity ---------------------------------------------------------------
    def sync_fills(self):
        if self.venue is None:
            return 0
        try:
            raw = self.venue.fills(limit=200).get("fills", [])
        except Exception as e:
            log.warning("fills sync failed: %s", e)
            return 0
        n = 0
        by_kid = {o["kalshi_order_id"]: o for o in self.ledger.orders(limit=5000) if o.get("kalshi_order_id")}
        for f in raw:
            kid = f.get("order_id")
            o = by_kid.get(kid)
            t = f.get("ticker", "")
            tg = desks.tags(desks.series_of(t))
            side = f.get("side", "yes")
            px = _num(f, f"{side}_price") or _num(f, "price") or D("0")
            row = {"fill_id": f.get("trade_id") or f.get("fill_id") or f"{kid}-{f.get('created_time')}",
                   "client_order_id": o["client_order_id"] if o else None, "kalshi_order_id": kid,
                   "ts": time.time(), "ticker": t, "event_ticker": desks.event_of(t),
                   "series_ticker": desks.series_of(t),
                   "desk": o["desk"] if o else tg["desk"], "category": o["category"] if o else tg["category"],
                   "league": tg["league"], "asset": tg["asset"],
                   "strategy_id": o["strategy_id"] if o else "external", "source": o["source"] if o else "external",
                   "side": side, "action": f.get("action", "buy"), "price": str(px),
                   "count": int(float(f.get("count_fp") or f.get("count") or 0)),
                   "fee": str(_num(f, "fee_cost") or D("0")),
                   "liquidity": "taker" if f.get("is_taker") else "maker"}
            self.ledger.insert_fill(row)
            n += 1
        return n

    def check_fee_types(self):
        """Read fee_type/fee_multiplier daily; a change on a traded series halts trading (§10)."""
        traded = {desks.series_of(p.ticker) for p in self.portfolio().positions}
        for st in traded:
            try:
                s = self.public.series(st)
            except Exception:
                continue
            cur = (s.get("fee_type"), str(s.get("fee_multiplier")))
            prev = self._fee_types.get(st)
            if prev and prev != cur:
                self.risk.observe_integrity("FEE_TYPE_CHANGE", f"{st}: {prev} -> {cur}")
            self._fee_types[st] = cur

    def _loop(self):
        last_sig = last_fee = 0.0
        while not self._stop.is_set():
            try:
                if self.venue is not None:
                    self.sync_fills()
                    pf = self.portfolio(fresh=True)
                    self.risk.observe_portfolio(pf)
                now = time.time()
                if now - last_sig > 45:
                    last_sig = now
                    self.run_signals()
                if now - last_fee > 6 * 3600 and self.venue is not None:
                    last_fee = now
                    self.check_fee_types()
            except Exception as e:
                log.warning("loop error: %s", e)
            self._stop.wait(5)

    def stop(self):
        self._stop.set()

    # ---- read models for the UI ------------------------------------------------------------------
    def status(self) -> dict:
        pf = self.portfolio()
        return {
            "mode": self.mode, "live": [],
            "nav": str(pf.nav), "cash": str(pf.cash), "day_pnl": str(pf.day_pnl),
            "exposure": str(sum((p.max_loss for p in pf.positions), D("0"))),
            "nav_assumed": self.venue is None,
            "kill": {"tripped": self.risk.kill.tripped, "reason": self.risk.kill.reason},
            "data": {"last_ok": self.public.last_ok, "last_error": self.public.last_error},
            "clock_ct": datetime.now(self.tz).strftime("%a %b %d %H:%M:%S CT"),
            "size_multiplier": str(self.risk.size_multiplier(pf)),
        }

    def strategies(self) -> list[dict]:
        out = []
        for s in self.registry.all():
            rep = self.report(s.id) or {}
            o = rep.get("oos") if isinstance(rep.get("oos"), dict) else {}
            caps = self.risk.strategy_caps.get(s.id) or self.risk.default_caps()
            out.append({**s.info(), "live": False,
                        "verdict": rep.get("verdict", "NO REPORT"), "oos_roi": o.get("roi"),
                        "oos_events": o.get("events"), "roi_ci95": o.get("roi_ci95"),
                        "v4_bar": rep.get("v4_bar", []), "n_signals": len(self.signals(s.id)),
                        "start_caps": {"exposure_usd": str(caps.exposure_usd), "max_contracts": caps.max_contracts,
                                       "daily_loss_usd": str(caps.daily_loss_usd)}})
        return out

    def ideas(self):
        return IDEAS

    def report(self, sid: str) -> Optional[dict]:
        f = self.s.reports_dir / f"{sid}.json"
        if f.exists():
            try:
                return json.loads(f.read_text())
            except json.JSONDecodeError:
                return None
        if sid == "mlb_model":
            ext = self.registry.get("mlb_model").external_report()
            return ext and {"strategy_id": sid, **ext}
        return None

    def report_md(self, sid: str) -> str:
        f = self.s.reports_dir / f"{sid}.md"
        return f.read_text() if f.exists() else ""

    def pnl(self) -> dict:
        """P&L split by desk, category, strategy and source (bot/manual/external); fees paid; interest separate."""
        fills = self.ledger.fills(limit=100000)
        sett = self.ledger.settlements()
        groups = {k: defaultdict(lambda: {"pnl": D("0"), "fees": D("0"), "fills": 0})
                  for k in ("desk", "category", "strategy_id", "source", "league", "asset")}
        fees = D("0")
        for f in fills:
            px, n, fee = D(f["price"]), int(f["count"]), D(f["fee"] or "0")
            fees += fee
            st = sett.get(f["ticker"])
            if st and st["result"] in ("yes", "no"):
                won = st["result"] == f["side"]
                sgn = 1 if f["action"] == "buy" else -1
                pnl = sgn * ((D("1") - px) * n if won else -px * n) - fee
            else:
                pnl = -fee
            for k, g in groups.items():
                key = f.get(k) or "-"
                g[key]["pnl"] += pnl
                g[key]["fees"] += fee
                g[key]["fills"] += 1
        return {"fees_paid": str(fees), "interest": "reported separately (Kalshi APY); never in backtest verdicts",
                **{k: {kk: {a: str(b) if not isinstance(b, int) else b for a, b in vv.items()} for kk, vv in g.items()}
                   for k, g in groups.items()}}

    def pm_stats(self) -> dict:
        picks = self.ledger.picks()
        with_q = [p for p in picks if p.get("q") and p.get("result") in ("yes", "no")]
        brier = None
        if with_q:
            brier = sum((D(p["q"]) - (1 if p["result"] == p["side"] else 0)) ** 2 for p in with_q) / len(with_q)
        clv = [D(p["close_price"]) - D(p["price"]) for p in picks if p.get("close_price")]
        warn = None
        last = clv[:100]
        if len(last) >= 20:
            import statistics as st
            m = float(sum(last) / len(last))
            sd = st.pstdev([float(x) for x in last]) or 0.0
            lcb90 = m - 1.2816 * sd / (len(last) ** 0.5)
            if lcb90 < 0:
                warn = f"CLV LCB90 {lcb90 * 100:.2f}c < 0 over the last {len(last)} picks (display-only warning)"
        by_tag = defaultdict(int)
        for p in picks:
            by_tag[p.get("tag") or "-"] += 1
        return {"picks": picks[:200], "n": len(picks), "brier_q": None if brier is None else str(brier),
                "clv_mean_cents": str(sum(clv) / len(clv) * 100) if clv else None, "governor_warning": warn,
                "by_tag": dict(by_tag)}
