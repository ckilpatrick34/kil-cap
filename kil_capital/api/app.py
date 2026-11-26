"""FastAPI app (spec v4 §8.4, §8.5).

Security: binds 127.0.0.1 only; Host-header check (DNS rebinding) and Origin check; a per-run
X-Kil-Token is required on every state-changing request.  The browser never sees keys and never
calls Kalshi directly.
"""
from __future__ import annotations

import logging
import secrets as pysecrets
import threading
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

log = logging.getLogger("kil.api")

from ..core import blocklist, desks
from .terminal import Terminal

WEB = Path(__file__).resolve().parent.parent / "web"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class LimitsIn(BaseModel):
    changes: dict


class PaperBuyIn(BaseModel):
    ticker: str
    side: str
    count: int = Field(ge=1, le=10000)
    strategy_id: Optional[str] = None
    fair: Optional[str] = None


class PaperCloseIn(BaseModel):
    ticker: str


class AutopilotIn(BaseModel):
    enabled: Optional[bool] = None
    min_edge: Optional[str] = None
    max_trade_usd: Optional[str] = None
    max_total_usd: Optional[str] = None
    max_positions: Optional[int] = Field(default=None, ge=1, le=100)


def create_app(terminal: Terminal | None = None, token: str | None = None, port: int = 8000) -> FastAPI:
    T = terminal or Terminal()
    TOKEN = token or pysecrets.token_urlsafe(24)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost", "testserver"}
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", "http://testserver"}
    app = FastAPI(title="Kil Capital Terminal", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.terminal = T
    app.state.token = TOKEN

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if host not in allowed_hosts:
            return JSONResponse({"error": "bad host"}, status_code=403)
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin not in allowed_origins:
                return JSONResponse({"error": "bad origin"}, status_code=403)
            if not pysecrets.compare_digest(request.headers.get("x-kil-token", ""), TOKEN):
                return JSONResponse({"error": "missing or bad X-Kil-Token"}, status_code=403)
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Frame-Options"] = "DENY"
        return resp

    if (WEB / "static").exists():
        app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

    def dec(x, name="value") -> Decimal:
        try:
            return Decimal(str(x))
        except (InvalidOperation, ValueError):
            raise HTTPException(400, f"bad {name}")

    # ---- UI / status ---------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index():
        html = (WEB / "index.html").read_text()
        return html.replace("__KIL_TOKEN__", TOKEN)

    @app.get("/api/health")
    def health():
        ok, bad = T.ledger.verify_chain()
        return {"ok": True, "audit_chain_ok": ok, "audit_bad_row": bad}

    @app.get("/api/status")
    def status():
        return T.status()

    @app.get("/api/tick")
    def tick():
        return {**T.status(), "risk": T.risk.utilization(T.portfolio())}

    # ---- markets -------------------------------------------------------------------------
    @app.get("/api/markets")
    def markets(desk: Optional[str] = None, q: Optional[str] = None, limit: int = 300):
        ms = T.scan_markets()
        out = []
        ql = (q or "").lower()
        for m in ms:
            tg = m.get("_tags") or {}
            if desk and tg.get("desk") != desk:
                continue
            if ql and ql not in (m.get("ticker", "") + " " + m.get("title", "") + " " +
                                 (m.get("yes_sub_title") or "")).lower():
                continue
            out.append({k: m.get(k) for k in ("ticker", "event_ticker", "title", "yes_sub_title", "close_time",
                                               "yes_bid_dollars", "yes_ask_dollars", "yes_bid", "yes_ask",
                                               "last_price_dollars", "volume", "volume_24h", "open_interest")}
                       | {"desk": tg.get("desk")})

        def vol(m):
            try:
                return float(m.get("volume_24h") or m.get("volume") or 0)
            except (TypeError, ValueError):
                return 0.0
        out.sort(key=vol, reverse=True)
        return {"markets": out[:limit], "desks": desks.DESKS, "last_ok": T.public.last_ok}

    def _not_blocked(ticker: str, m: dict):
        if blocklist.check_market({**m, "ticker": ticker}).blocked:
            raise HTTPException(404, "market hidden (BLOCKLIST_MSU)")

    @app.get("/api/markets/{ticker}")
    def market(ticker: str):
        m = T.public.market(ticker)
        _not_blocked(ticker, m)
        return m

    @app.get("/api/markets/{ticker}/book")
    def book(ticker: str):
        _not_blocked(ticker, T.public.market(ticker))
        return T.public.orderbook(ticker)

    @app.get("/api/markets/{ticker}/candles")
    def candles(ticker: str, span: str = "1d"):
        import time as _t
        m = T.public.market(ticker)
        _not_blocked(ticker, m)
        secs, period = {"6h": (6 * 3600, 1), "1d": (86400, 1), "7d": (7 * 86400, 60), "30d": (30 * 86400, 1440)}.get(span, (86400, 1))
        st = m.get("series_ticker") or desks.series_of(m.get("event_ticker", ticker))
        end = int(_t.time())
        return {"candles": T.public.candles(st, ticker, end - secs, end, period)}

    @app.get("/api/markets/{ticker}/trades")
    def trades(ticker: str):
        _not_blocked(ticker, T.public.market(ticker))
        return T.public.trades(ticker, limit=100)

    @app.get("/api/orders")
    def orders(status: Optional[str] = None):
        return {"orders": T.ledger.orders(status)}

    # ---- portfolio / pnl ------------------------------------------------------------------
    @app.get("/api/positions")
    def positions():
        pf = T.portfolio()
        return {"positions": [{"ticker": p.ticker, "side": p.side, "count": p.count, "avg_price": str(p.avg_price),
                               "max_loss": str(p.max_loss), "desk": p.desk, "strategy_id": p.strategy_id,
                               "source": p.source} for p in pf.positions],
                "nav": str(pf.nav), "nav_assumed": T.venue is None}

    @app.get("/api/fills")
    def fills():
        return {"fills": T.ledger.fills(limit=500)}

    @app.get("/api/pnl")
    def pnl():
        return T.pnl()

    # ---- risk / kill -------------------------------------------------------------------------
    @app.get("/api/risk")
    def risk():
        return {**T.risk.utilization(T.portfolio()),
                "limit_values": {k: str(v) for k, v in T.risk.L.__dict__.items()},
                "blocklist_review": blocklist.review_log.items[-50:]}

    @app.put("/api/risk/limits")
    def tighten(l: LimitsIn):
        from ..config import LimitError
        try:
            new = T.limits.tighten("carson", **l.changes)
        except LimitError as e:
            raise HTTPException(400, str(e))
        return {k: str(v) for k, v in new.__dict__.items()}

    # ---- strategies (recommend-only) ------------------------------------------------------------------
    @app.get("/api/strategies")
    def strategies():
        return {"strategies": T.strategies(), "ideas": T.ideas(), "mode": T.mode}

    @app.get("/api/strategies/{sid}/signals")
    def signals(sid: str):
        return {"signals": T.signals(sid), "recorded": T.ledger.signals(sid, 50)}

    # ---- trade ideas / paper trading / autopilot (simulated money only) ----------------------------
    @app.get("/api/opportunities")
    def opportunities(limit: int = 60):
        return {"opportunities": T.opportunities(limit), "last_scan_ts": T.last_scan_ts,
                "mode": T.mode, "data": {"last_ok": T.public.last_ok, "last_error": T.public.last_error}}

    @app.get("/api/slate")
    def slate():
        st = T.slate.snapshot()
        return {**st, "games": [{k: v for k, v in g.items() if k != "contracts"} | {
            "n_contracts": len(g["contracts"]), "n_trades": sum(bool(c.get("tradeable")) for c in g["contracts"])}
            for g in st.get("games", [])]}

    @app.get("/api/slate/game/{gid}")
    def slate_game(gid: str):
        for g in T.slate.snapshot().get("games", []):
            if g["id"] == gid:
                return g
        raise HTTPException(404, "game not on the slate")

    @app.get("/api/learn")
    def learn_status():
        return T.learn_status()

    @app.get("/api/crypto")
    def crypto():
        return T.crypto.snapshot()

    @app.post("/api/refresh")
    def refresh():
        def go():
            for fn in (T.refresh_slate, T.refresh_crypto):
                try:
                    fn()
                except Exception as e:
                    log.warning("manual refresh: %s", e)
        threading.Thread(target=go, daemon=True).start()
        return {"ok": True}

    @app.get("/api/paper")
    def paper():
        return T.paper_summary()

    @app.post("/api/paper/buy")
    def paper_buy(b: PaperBuyIn):
        info = T.market_info(b.ticker)
        if blocklist.check_market({**info.raw, "ticker": b.ticker}).blocked:
            raise HTTPException(404, "market hidden (BLOCKLIST_MSU)")
        side = b.side.lower()
        ask = info.yes_ask if side == "yes" else (None if info.yes_bid is None else Decimal("1") - info.yes_bid)
        if ask is None or not (Decimal("0") < ask < Decimal("1")):
            raise HTTPException(400, "no ask to buy from right now")
        try:
            return T.paper.buy(ticker=b.ticker, side=side, price=ask, count=b.count, strategy_id=b.strategy_id or "manual",
                               title=info.title, fair=b.fair)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/paper/close")
    def paper_close(c: PaperCloseIn):
        p = T.paper.positions.get(c.ticker)
        if not p:
            raise HTTPException(404, "no paper position")
        yb, ya = T.quote(c.ticker)
        bid = yb if p["side"] == "yes" else (None if ya is None else Decimal("1") - ya)
        try:
            return T.paper.close(c.ticker, bid if bid is not None else 0)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/paper/reset")
    def paper_reset():
        T.paper.reset()
        T.ledger.audit("paper.reset", "carson", {}, "ok")
        return T.paper_summary()

    @app.post("/api/autopilot")
    def autopilot(a: AutopilotIn):
        for name in ("min_edge", "max_trade_usd", "max_total_usd"):
            v = getattr(a, name)
            if v is not None and dec(v, name) <= 0:
                raise HTTPException(400, f"{name} must be positive")
        out = T.paper.set_auto(**a.model_dump())
        T.ledger.audit("autopilot.set", "carson", {**out, "paper_only": True}, "ok")
        if a.enabled is not None:
            T.paper.note("Autopilot ON (paper money only)" if out["enabled"] else "Autopilot OFF")
        if a.enabled:
            threading.Thread(target=T.paper_tick, daemon=True).start()
        return out

    # ---- backtests / audit / PM -------------------------------------------------------------------
    @app.get("/api/backtests")
    def backtests():
        out = []
        for s in T.registry.all():
            r = T.report(s.id) or {}
            o = r.get("oos") if isinstance(r.get("oos"), dict) else {}
            out.append({"strategy_id": s.id, "verdict": r.get("verdict", "NO REPORT"), "events": o.get("events"),
                        "roi": o.get("roi"), "generated_at": r.get("generated_at")})
        return {"reports": out}

    @app.get("/api/backtests/{sid}")
    def backtest(sid: str):
        return {"report": T.report(sid), "markdown": T.report_md(sid)}

    @app.get("/api/audit")
    def audit(limit: int = 300):
        ok, bad = T.ledger.verify_chain()
        return {"rows": T.ledger.audit_rows(limit), "chain_ok": ok, "bad_row": bad}

    @app.get("/api/pm/picks")
    def pm_picks():
        return T.pm_stats()

    return app


def main():  # pragma: no cover - launched by start.command
    import uvicorn
    from ..config import SETTINGS
    app = create_app(port=SETTINGS.port)
    print(f"Kil Capital Terminal: http://127.0.0.1:{SETTINGS.port}  (RESEARCH mode)")
    uvicorn.run(app, host="127.0.0.1", port=SETTINGS.port, log_level="warning")


if __name__ == "__main__":  # pragma: no cover
    main()
