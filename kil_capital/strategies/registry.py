"""Strategy registry.  Registering a plugin here gives it a backtest, signals and a live gate."""
from __future__ import annotations

from pathlib import Path

from .bracket import BracketArb
from .elo_sports import EloSports
from .external import MlbModel, PmCarson
from .late_favorite import LateFavoriteCrypto, LateFavoriteSports, LateFavoriteWeather
from .longshot import LongshotFade
from .market_maker import MarketMaker
from .sharp_line import SharpLineValue

CLASSES = (BracketArb, LongshotFade, LateFavoriteSports, LateFavoriteWeather, LateFavoriteCrypto,
           MarketMaker, SharpLineValue, EloSports)

# Catalog entries with no plugin yet (status: idea) -- shown on STRATEGIES, cannot go live.
IDEAS = [
    {"id": "S3", "name": "Decided-but-unsettled sweep", "evidence": "PLAUSIBLE", "status": "idea"},
    {"id": "S5", "name": "Slow public data (AAA gas, TSA)", "evidence": "UNPROVEN", "status": "idea"},
    {"id": "C1", "name": "Combo/parlay seller (RFQ maker)", "evidence": "PROVEN on history, fills unproven", "status": "idea"},
    {"id": "X2", "name": "Info-shock latency on thin markets", "evidence": "PLAUSIBLE (thin only)", "status": "idea"},
    {"id": "X3", "name": "Pre-catalyst futures optionality", "evidence": "UNPROVEN", "status": "idea"},
    {"id": "X4", "name": "Reverse-longshot pockets", "evidence": "UNPROVEN", "status": "idea"},
    {"id": "X5", "name": "OT / extras markets vs scoring model", "evidence": "UNPROVEN", "status": "idea"},
    {"id": "B1-G", "name": "In-game benchmark-gap", "evidence": "fade NEGATIVE; gap variant only", "status": "idea"},
    {"id": "E1", "name": "Econ structure (S1/S2/S3 on CPI/Fed)", "evidence": "forecasting NEGATIVE", "status": "idea"},
    {"id": "P1", "name": "Politics/culture S2 tilt", "evidence": "PROVEN in aggregate (S2)", "status": "idea"},
    {"id": "CR3", "name": "Crypto tail NO from Kalshi calibration", "evidence": "PLAUSIBLE", "status": "idea"},
    {"id": "CR4", "name": "Crypto ladder maker", "evidence": "Low for this book", "status": "idea"},
    {"id": "CR5", "name": "Year-end fee-free carry (KXBTCY/KXETHY)", "evidence": "UNPROVEN", "status": "idea"},
    {"id": "CR6", "name": "One-touch seller vs barrier model", "evidence": "UNPROVEN", "status": "idea"},
    {"id": "CR7", "name": "15-minute up/down", "evidence": "Likely unprofitable: don't build first", "status": "idea"},
    {"id": "CR8", "name": "60-s averaging window", "evidence": "UNPROVEN: research only", "status": "idea"},
]


class Registry:
    def __init__(self, mlb_model_dir: Path | None = None):
        self._s = {c.id: c() for c in CLASSES}
        self._s["mlb_model"] = MlbModel(model_dir=mlb_model_dir)
        self._s["pm_carson"] = PmCarson()

    def get(self, sid: str):
        return self._s.get(sid)

    def is_known(self, sid: str) -> bool:
        return sid in self._s

    def ids(self) -> list[str]:
        return list(self._s)

    def all(self):
        return list(self._s.values())

    def bots(self):
        """Strategies that produce automated signals (excludes manual and read-only external)."""
        return [s for k, s in self._s.items() if k not in ("pm_carson", "mlb_model")]
