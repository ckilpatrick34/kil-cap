"""X1 sharp_line_value: thin Kalshi markets vs de-vigged Pinnacle/consensus (The Odds API).

Main game lines are EXCLUDED (Kalshi main lines are about as sharp as Pinnacle).  Trade only
the 1-3% edge band (above 3% realized edge collapses vs the Pinnacle close).

Needs an Odds API plan (spec §12 Q3).  Without ODDS_API_KEY in .env this strategy reports
NO DATA and produces no signals.  Historical odds come with every paid plan; historical calls
cost 10 credits per region per market.
"""
from __future__ import annotations

from decimal import Decimal

from .base import Strategy

D = Decimal


def devig_two_way(dec_odds_a: float, dec_odds_b: float) -> tuple[float, float]:
    """Multiplicative de-vig of a two-way market from decimal odds."""
    ia, ib = 1.0 / dec_odds_a, 1.0 / dec_odds_b
    s = ia + ib
    return ia / s, ib / s


def american_to_decimal(a: float) -> float:
    return 1 + (a / 100.0 if a > 0 else 100.0 / -a)


def in_trade_band(edge: Decimal, lo=D("0.01"), hi=D("0.03")) -> bool:
    return lo <= edge <= hi


MAIN_LINE_SERIES = ("KXMLBGAME", "KXNBAGAME", "KXNFLGAME", "KXNCAAFGAME", "KXNCAAMBGAME")


class SharpLineValue(Strategy):
    id = "sharp_line_value"
    name = "Thin-market sharp anchor"
    catalog_id = "X1"
    evidence = "PLAUSIBLE"
    status = "backtesting"
    is_model = True
    needs_paid_data = "The Odds API (paid plan for historical, spec §12 Q3)"
    notes = "Main lines excluded. Trade only the 1-3% band. NO DATA until an Odds API plan is chosen."

    @classmethod
    def default_params(cls):
        return {"band_lo": D("0.01"), "band_hi": D("0.03"), "contracts": 5}

    def accepts(self, m):
        return (m.get("series_ticker") or "").upper() not in MAIN_LINE_SERIES

    def decisions(self, m):
        return []   # requires historical sharp lines; see module doc
