"""External / manual strategy slots.

- `mlb_model`: Carson's MLB model.  Read-only: reads kil_report.json / report.json from
  KIL_MLB_MODEL_DIR (spec v4 §5.1).  It produces no orders on its own here.
- `pm_carson`: the manual desk (§5.2).  Manual SEND works only while pm_carson is enabled live,
  and each order also needs a typed confirmation in the ticket.
"""
from __future__ import annotations

import json
from pathlib import Path

from .base import Strategy


class MlbModel(Strategy):
    id = "mlb_model"
    name = "Carson's MLB model"
    catalog_id = "MLB"
    desk = "MLB"
    evidence = "PENDING"
    status = "backtesting"
    is_model = True
    notes = ("Judge by §6: ROI after KXMLBGAME fees (M=0.5, maker fees too), Brier/log loss vs Kalshi price, "
             "CLV vs close. If it can't beat the main line, use it as the prior inside X1/X2 on props/F5.")

    def __init__(self, model_dir: Path | None = None, **p):
        super().__init__(**p)
        self.model_dir = Path(model_dir) if model_dir else None

    def external_report(self) -> dict | None:
        if not self.model_dir:
            return None
        for cand in ("kil_report.json", "report.json", "backtest/kil_report.json", "backtest/report.json"):
            f = self.model_dir / cand
            if f.exists():
                try:
                    return json.loads(f.read_text())
                except json.JSONDecodeError:
                    return {"verdict": "NO DATA", "error": f"unreadable {cand}"}
        return None


class PmCarson(Strategy):
    id = "pm_carson"
    name = "PM-Carson (manual)"
    catalog_id = "PM"
    desk = "PM-CARSON"
    evidence = "Carson's own record"
    status = "backtesting"
    notes = "Manual trades: source=manual, desk=PM-CARSON, never mixed into bot statistics."
