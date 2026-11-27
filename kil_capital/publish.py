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
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import SETTINGS
from .core import blocklist
from .crypto.desk import CryptoDesk
from .autotrack import AutoTrack
from .book import Book, candidates as book_candidates
from .research.recorder import Recorder
from .budget import FAVOURITE, allocate
from .sports import calibrate, learn, segments
from .sports.leagues import SERIES_TO_LEAGUE
from .sports.slate import Slate
from .ufc.desk import UfcDesk
from .venue.public import PublicClient

log = logging.getLogger("kil.publish")
EQUITY = float(os.environ.get("KIL_BANKROLL", "100"))      # sizing bankroll for Kelly stakes
MAX_TRADE = float(os.environ.get("KIL_MAX_TRADE", "10"))       # per bet
BUDGET = float(os.environ.get("KIL_BUDGET", "100"))            # total open risk for one slate
VERSION = os.environ.get("GITHUB_SHA", "local")[:7]
MIN_EDGE = float(os.environ.get("KIL_MIN_EDGE", "0.03"))
MAX_EDGE = float(os.environ.get("KIL_MAX_EDGE", "0.15"))   # bigger gaps are far likelier model error than mispricing
DAYS_AHEAD = int(os.environ.get("KIL_DAYS_AHEAD", "6"))   # today + 6 = the "This week" view


def _finite(x):
    """Browsers reject NaN/Infinity in JSON and then load nothing, so non-finite numbers become null."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    return x


KINDS = ("winner", "spread", "total")


def _enrich(picks: list[dict], games: list[dict]) -> list[dict]:
    """Copy each pick's teams (name, rank, conference) and market type onto it so the page filters without joins."""
    gmap = {g["id"]: g for g in games}
    out = []
    for p in picks:
        g = gmap.get(p.get("game_id"))
        kind = KINDS[SERIES_TO_LEAGUE[p["ticker"].split("-")[0]][1]] if p["ticker"].split("-")[0] in SERIES_TO_LEAGUE \
            else ("crypto" if p.get("desk") == "crypto" else None)
        teams = [{k: (g.get(s) or {}).get(k) for k in ("name", "abbr", "nick", "rank", "conf")} for s in ("away", "home")] if g else []
        out.append({**p, "kind": kind, "teams": teams})
    return out


def _one_per_game(picks: list[dict]) -> list[dict]:
    """Both sides of a game (OKC NO = MIL YES) and neighbouring strikes are one position, not several:
    keep the best pick per game and market kind. Input is sorted best-first."""
    seen, out = set(), []
    for p in picks:
        k = (p["game_id"], p["ticker"].split("-")[0]) if p.get("game_id") else None   # series = market kind
        if k is None or k not in seen:
            seen.add(k)
            out.append(p)
    return out


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
             for r in (slate.track.rows.values() if slate.track else ()) if r["result"] is not None]
    try:
        picks += json.loads((data_dir / "bigvin_picks.json").read_text())
    except (OSError, ValueError):
        pass
    (data_dir / "segments.json").write_text(json.dumps(segments.build_table(picks), indent=1))
    cal = calibrate_from_track(slate, data_dir)
    marker.write_text(local.date().isoformat())
    (data_dir / "learn_status.json").write_text(json.dumps({"ts": time.time(), "date": local.date().isoformat()}))
    slate._ratings.clear()
    return {"promoted": [r["league"] for r in res if r.get("promoted")], "calibration": cal}


def _graded(slate: Slate) -> list[dict]:
    return [{"fair": r["fair"], "price": r["price"], "won": r["result"] == "W", "ts": r["logged"],
             "model_fair": r.get("model_fair"), "mid": r.get("mid")}
            for r in (slate.track.rows.values() if slate.track else ()) if r["result"] is not None]


def calibrate_from_track(slate: Slate, data_dir: Path) -> dict:
    """Nightly: refit how much to trust the model vs the Kalshi price from our own graded picks."""
    path = data_dir / "calibration.json"
    old = calibrate.load(path)
    res = calibrate.fit(_graded(slate), float(old.get("w", calibrate.DEFAULT_W)))
    hist = (old.get("history") or [])[-60:] + [{k: v for k, v in res.items() if k != "history"}]
    path.write_text(json.dumps({**res, "history": hist}, indent=1))
    return res


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
    sports = slate.refresh(min_edge=MIN_EDGE, equity=EQUITY, max_trade=MAX_TRADE, days_ahead=DAYS_AHEAD)
    cry = crypto.refresh(min_edge=MIN_EDGE, equity=EQUITY, max_trade=MAX_TRADE)
    picks = [{**s, "desk": "sports"} for s in sports["signals"]] + \
            [{**s, "desk": "crypto", "exp_profit": round(s["count"] * (s["fair"] - s["price"]), 2)}
             for s in cry["signals"]]
    picks = sorted(filter(_allowed, picks), key=lambda s: -s.get("exp_profit", 0))
    suspect = [p for p in picks if p["edge"] > MAX_EDGE]   # kept visible for review, never recommended
    picks = [p for p in picks if p["edge"] <= MAX_EDGE]
    picks = _one_per_game(picks)
    games = [g for g in sports["games"] if _allowed({"title": g["name"]})]
    picks = _enrich(picks, games)
    picks = allocate(picks, EQUITY, BUDGET, MAX_TRADE, FAVOURITE)   # same default slate as the dashboard
    auto, mids = AutoTrack(data_dir / "autotrack.json", EQUITY, BUDGET, MAX_TRADE), {}
    try:
        mids = {c["ticker"]: (c["yes_bid"] + c["yes_ask"]) / 2 for g in games for c in g.get("contracts", [])
                if c.get("yes_bid") and c.get("yes_ask")}
        mids.update({r["ticker"]: (r["yes_bid"] + r["yes_ask"]) / 2 for v in cry["products"].values()
                     for r in v["kalshi"] if r.get("yes_bid") and r.get("yes_ask")})
        auto.mark(mids)
        auto.grade(public)
        auto.enter(picks, VERSION)
        auto.save()
    except Exception as e:  # the paper tracker must never blank the dashboard
        errors.append(f"autotrack: {e}")
    book = Book(data_dir / "book_v2.json", EQUITY, EQUITY, MAX_TRADE)
    try:
        book.mark(mids)
        book.grade(public)
        cands = book_candidates(games)
        book.enter(cands, VERSION)
        book.save()
        flagged = {c["ticker"]: c["sleeve"] for c in cands} | {b["ticker"]: b["sleeve"] for b in book.bets}
        for g in games:
            for c in g.get("contracts", []):
                if c["ticker"] in flagged:
                    c["book_sleeve"] = flagged[c["ticker"]]
    except Exception as e:  # the book must never blank the dashboard
        errors.append(f"book: {e}")
    try:
        ufc = UfcDesk(public, data_dir).refresh(max_trade=MAX_TRADE)
    except Exception as e:  # the UFC tab must never blank the dashboard
        ufc = {"fights": [], "errors": [f"ufc: {e}"]}
    try:   # record-only research data; never orders, never allowed to blank the dashboard
        recorders = Recorder(public, data_dir).run()
    except Exception as e:
        recorders = {"errors": [str(e)]}
        errors.append(f"recorders: {e}")
    lg = learn.load(data_dir / "learn_log.json")
    status = learn.load(data_dir / "learn_status.json")
    cal = calibrate.load(data_dir / "calibration.json")
    return {
        "generated": datetime.now(timezone.utc).isoformat(), "build_seconds": round(time.time() - t0, 1),
        "mode": "RECOMMEND-ONLY", "bankroll": EQUITY, "budget": BUDGET, "version": VERSION, "kelly_fraction": segments.KELLY_FRACTION, "max_trade": MAX_TRADE, "min_edge": MIN_EDGE, "max_edge": MAX_EDGE,
        "picks": picks, "suspect": suspect, "games": games, "track": sports.get("track", {}),
        "crypto": {k: {kk: v[kk] for kk in ("spot", "vol_annual", "rsi14", "sma50", "sma200", "chart",
                                             "strategies", "kalshi")} for k, v in cry["products"].items()},
        "learn": {"params": learn.load(data_dir / "model_params.json"),
                  "log": (lg if isinstance(lg, list) else [])[-14:], "ran_now": learned,
                  "last_ts": status.get("ts"), "w_market": calibrate.weight(data_dir / "calibration.json"),
                  "calibration": {k: cal.get(k) for k in ("n", "w", "promoted", "reason", "challenger",
                                                          "champion_logloss", "challenger_logloss", "ts")},
                  "deciles": calibrate.deciles(_graded(slate))},
        "autotrack": auto.summary(),
        "book": book.summary(),
        "ufc": {k: v for k, v in ufc.items() if k != "errors"},
        "recorders": recorders,
        "ratings_n": sports.get("ratings_n", {}),
        "errors": errors + sports.get("errors", []) + cry.get("errors", []) + ufc.get("errors", []),
    }


def dump(state: dict) -> str:
    return json.dumps(_finite(state), separators=(",", ":"), default=str, allow_nan=False)


def main():  # pragma: no cover - exercised in GitHub Actions
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data/state.json")
    ap.add_argument("--data", default=str(SETTINGS.data_dir))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    state = build(PublicClient(SETTINGS.kalshi_base_url, SETTINGS.public_req_per_sec), Path(a.data))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dump(state))
    print(f"wrote {out}: {len(state['picks'])} picks, {len(state['games'])} games, {len(state['errors'])} errors")


if __name__ == "__main__":  # pragma: no cover
    main()
