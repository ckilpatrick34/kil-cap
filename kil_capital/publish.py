"""Headless one-shot publisher for the GitHub-hosted dashboard.

Runs in GitHub Actions on a schedule: refreshes the game slate and crypto desk from public data
(Kalshi market data, ESPN, weather, candles), runs the nightly learner once per day, and writes one
JSON file the static dashboard reads. RECOMMEND-ONLY: no Kalshi account, no keys, no orders.

    python -m kil_capital.publish --out site/data/state.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import SETTINGS
from .core import blocklist
from .crypto.desk import CryptoDesk
from .sports import learn, segments
from .sports.slate import Slate
from .venue.public import PublicClient

log = logging.getLogger("kil.publish")
EQUITY = float(os.environ.get("KIL_BANKROLL", "1000"))     # sizing bankroll for Kelly stakes
MAX_TRADE = float(os.environ.get("KIL_MAX_TRADE", "50"))
MIN_EDGE = float(os.environ.get("KIL_MIN_EDGE", "0.03"))


def _allowed(s: dict) -> bool:
    return not blocklist.is_blocked({"ticker": s.get("ticker", ""), "title": s.get("title", "")})


def _learn_if_due(slate: Slate, data_dir: Path, tz: ZoneInfo) -> dict | None:
    """Nightly, after 4 AM Central, once per local day (marker file in the persisted data dir)."""
    local = datetime.now(tz)
    marker = data_dir / "learned_on.txt"
    done = marker.read_text().strip() if marker.exists() else ""
    if local.hour < 4 or done == local.date().isoformat():
        return None
    res = learn.nightly(slate.espn, data_dir, local.date(), slate.leagues)
    picks = [{"league": r["league"], "kind": r["kind"], "edge": r["edge"], "price": r["price"],
              "won": r["result"] == "W", "ts": r["logged"]}
             for r in slate.track.rows.values() if r["result"] is not None]
    try:
        picks += json.loads((data_dir / "bigvin_picks.json").read_text())
    except (OSError, ValueError):
        pass
    (data_dir / "segments.json").write_text(json.dumps(segments.build_table(picks), indent=1))
    marker.write_text(local.date().isoformat())
    slate._ratings.clear()
    return {"promoted": [r["league"] for r in res if r.get("promoted")]}


def build(public, data_dir: Path, tz_name: str = SETTINGS.timezone) -> dict:
    tz = ZoneInfo(tz_name)
    data_dir.mkdir(parents=True, exist_ok=True)
    slate, crypto = Slate(public, data_dir, tz_name), CryptoDesk(public, data_dir)
    errors, learned = [], None
    try:
        learned = _learn_if_due(slate, data_dir, tz)
    except Exception as e:  # a bad learning night must never blank the dashboard
        errors.append(f"learn: {e}")
    t0 = time.time()
    sports = slate.refresh(min_edge=MIN_EDGE, equity=EQUITY, max_trade=MAX_TRADE)
    cry = crypto.refresh(min_edge=MIN_EDGE, equity=EQUITY, max_trade=MAX_TRADE)
    picks = [{**s, "desk": "sports"} for s in sports["signals"]] + \
            [{**s, "desk": "crypto", "exp_profit": round(s["count"] * (s["fair"] - s["price"]), 2)}
             for s in cry["signals"]]
    picks = sorted(filter(_allowed, picks), key=lambda s: -s.get("exp_profit", 0))
    games = [g for g in sports["games"] if _allowed({"title": g["name"]})]
    lg = learn.load(data_dir / "learn_log.json")
    return {
        "generated": datetime.now(timezone.utc).isoformat(), "build_seconds": round(time.time() - t0, 1),
        "mode": "RECOMMEND-ONLY", "bankroll": EQUITY, "kelly_fraction": segments.KELLY_FRACTION, "max_trade": MAX_TRADE, "min_edge": MIN_EDGE,
        "picks": picks, "games": games, "track": sports.get("track", {}),
        "crypto": {k: {kk: v[kk] for kk in ("spot", "vol_annual", "rsi14", "sma50", "sma200", "chart",
                                             "strategies", "kalshi")} for k, v in cry["products"].items()},
        "learn": {"params": learn.load(data_dir / "model_params.json"),
                  "log": (lg if isinstance(lg, list) else [])[-14:], "ran_now": learned},
        "ratings_n": sports.get("ratings_n", {}),
        "errors": errors + sports.get("errors", []) + cry.get("errors", []),
    }


def main():  # pragma: no cover - exercised in GitHub Actions
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data/state.json")
    ap.add_argument("--data", default=str(SETTINGS.data_dir))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    state = build(PublicClient(SETTINGS.kalshi_base_url, SETTINGS.public_req_per_sec), Path(a.data))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(state, separators=(",", ":"), default=str))
    print(f"wrote {out}: {len(state['picks'])} picks, {len(state['games'])} games, {len(state['errors'])} errors")


if __name__ == "__main__":
    main()
