"""Settings and risk limits (spec v4 §7).

Limits can be TIGHTENED at runtime from the UI (see RiskLimitsManager.tighten) and
RAISED only by editing the defaults below and restarting.  Every change is audited.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, replace
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = Decimal


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"  # never bind anything else (§8.5)
    port: int = int(_env("KIL_PORT", "8000"))
    data_dir: Path = Path(_env("KIL_DATA_DIR", str(ROOT / "data")))
    reports_dir: Path = Path(_env("KIL_REPORTS_DIR", str(ROOT / "reports")))
    # Kalshi production API (public market data is read-only and free).
    kalshi_base_url: str = _env("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
    kalshi_ws_url: str = _env("KALSHI_WS_URL", "wss://api.elections.kalshi.com/trade-api/ws/v2")
    mlb_model_dir: Path = Path(_env("KIL_MLB_MODEL_DIR", str(ROOT.parent / "mlb-model")))
    public_req_per_sec: float = 2.0  # §9: pace unauthenticated calls at ~2 req/s
    rest_latency_s: float = 2.0  # backtest taker latency default (§6.1)
    timezone: str = "America/Chicago"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kil_capital.sqlite"


@dataclass(frozen=True)
class RiskLimits:
    """All §7.1 / §7.3 / §4.4 defaults.  Fractions are of NAV unless named *_usd."""

    daily_loss_frac: Decimal = D("0.05")          # built
    drawdown_kill_frac: Decimal = D("0.20")       # built
    drawdown_halve_frac: Decimal = D("0.10")      # proposed
    per_market_frac: Decimal = D("0.05")          # built
    per_event_frac: Decimal = D("0.10")           # built
    max_order_contracts: int = 500                # built
    max_order_loss_usd: Decimal = D("250")        # built
    fat_finger_cents: Decimal = D("0.10")         # built: within 10c of mid when a book exists
    manual_daily_loss_usd: Decimal = D("100")     # built (PM-Carson)
    per_category_frac: Decimal = D("0.25")        # proposed
    cluster_frac: Decimal = D("0.15")             # proposed
    team_frac: Decimal = D("0.03")                # proposed
    player_frac: Decimal = D("0.015")             # proposed
    league_frac: Decimal = D("0.30")              # proposed
    crypto_macro_frac: Decimal = D("0.05")        # proposed
    crypto_per_expiry_frac: Decimal = D("0.015")  # proposed
    bankroll_at_risk_frac: Decimal = D("0.60")    # proposed (keep >=10% cash)
    min_cash_frac: Decimal = D("0.10")            # proposed
    settlement_source_frac: Decimal = D("0.10")   # proposed
    s1_naked_leg_usd: Decimal = D("100")          # proposed: min($100, 1% NAV)
    s1_naked_leg_frac: Decimal = D("0.01")
    crypto_no_entry_window_s: int = 60            # proposed: never enter inside final 60s
    spot_feed_gap_kill_s: int = 10                # proposed
    # §7.3 starting caps for a newly enabled strategy (Carson can override at enable).
    start_exposure_usd: Decimal = D("500")
    start_exposure_frac: Decimal = D("0.05")
    start_max_contracts: int = 25
    start_daily_loss_usd: Decimal = D("50")
    kelly_k: Decimal = D("0.10")
    pm_kelly_k: Decimal = D("0.10")


# Which direction is "tighter" for each limit: everything is "lower is tighter".
TIGHTEN_LOWER = {f.name for f in fields(RiskLimits)} - {"kelly_k", "pm_kelly_k"}


class LimitError(ValueError):
    pass


class RiskLimitsManager:
    """Holds the effective limits.  `tighten` may only lower values; raising needs config + restart."""

    def __init__(self, base: RiskLimits | None = None, audit=None):
        self._base = base or RiskLimits()
        self._current = self._base
        self._audit = audit

    @property
    def current(self) -> RiskLimits:
        return self._current

    @property
    def base(self) -> RiskLimits:
        return self._base

    def tighten(self, actor: str, **changes) -> RiskLimits:
        upd = {}
        for k, v in changes.items():
            if k not in {f.name for f in fields(RiskLimits)}:
                raise LimitError(f"unknown limit {k}")
            cur = getattr(self._current, k)
            newv = type(cur)(str(v)) if isinstance(cur, Decimal) else type(cur)(v)
            if newv < 0:
                raise LimitError(f"{k} cannot be negative")
            if newv > cur:
                raise LimitError(f"{k}: raising limits is only allowed in config.py plus a restart")
            upd[k] = newv
        self._current = replace(self._current, **upd)
        if self._audit:
            self._audit("limits.tighten", actor, {k: str(v) for k, v in upd.items()}, "ok")
        return self._current


SETTINGS = Settings()
