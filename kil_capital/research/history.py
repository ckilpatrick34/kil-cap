"""Multi-season game history in one common schema, so every league can feed the same feature builder.

Row schema (home team's point of view):
    id, league, season, ts, week, playoff, home, away, hs, as_, neutral,
    spread  - market's expected home margin at close (home favoured => positive), or None
    total   - market closing total, or None
    rest_h, rest_a, div, dome, temp, wind, qb_h, qb_a   (None when a source doesn't have them)

Sources:
  * nflverse games.csv (public, GitHub): every NFL game since 1999 with closing spread/total, rest,
    roof, weather, starting QBs. Downloaded once into data/raw/.
  * ESPN history (the app's own feed) via `from_espn`, for the leagues nflverse doesn't cover."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path

import httpx

NFLVERSE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def nflverse(raw_dir: Path, refresh: bool = False) -> list[dict]:
    path = Path(raw_dir) / "nflverse_games.csv"
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        r = httpx.get(NFLVERSE_URL, timeout=60, follow_redirects=True)
        r.raise_for_status()
        path.write_text(r.text)
    out = []
    for g in csv.DictReader(io.StringIO(path.read_text())):
        hs, as_ = _f(g["home_score"]), _f(g["away_score"])
        if hs is None or as_ is None:
            continue                                  # not played yet
        ts = datetime.fromisoformat(g["gameday"]).replace(tzinfo=timezone.utc).timestamp()
        out.append({"id": g["game_id"], "league": "nfl", "season": int(g["season"]), "ts": ts,
                    "week": int(g["week"]), "playoff": g["game_type"] != "REG",
                    "home": g["home_team"], "away": g["away_team"], "hs": hs, "as_": as_,
                    "neutral": g["location"] == "Neutral",
                    "spread": _f(g["spread_line"]), "total": _f(g["total_line"]),
                    "rest_h": _f(g["home_rest"]), "rest_a": _f(g["away_rest"]),
                    "div": g["div_game"] == "1", "dome": g["roof"] in ("dome", "closed"),
                    "temp": _f(g["temp"]), "wind": _f(g["wind"]),
                    "qb_h": g["home_qb_id"] or None, "qb_a": g["away_qb_id"] or None})
    return sorted(out, key=lambda r: (r["ts"], r["id"]))


def from_espn(league: str, games: list[dict]) -> list[dict]:
    """Adapt the app's ESPN history dicts (see sports/espn.py) to the common schema."""
    out = []
    for g in games:
        h, a = g["home"], g["away"]
        if h.get("score") is None or a.get("score") is None or g.get("start_ts") is None:
            continue
        odds = g.get("odds") or {}
        sh = odds.get("spread_home")
        season = datetime.fromtimestamp(g["start_ts"], timezone.utc)
        out.append({"id": str(g.get("id")), "league": league,
                    "season": season.year if season.month >= 7 else season.year - 1,
                    "ts": g["start_ts"], "week": 0, "playoff": False, "home": h["id"], "away": a["id"],
                    "hs": float(h["score"]), "as_": float(a["score"]), "neutral": bool(g.get("neutral")),
                    "spread": -sh if sh is not None else None, "total": odds.get("total"),
                    "rest_h": None, "rest_a": None, "div": False, "dome": False, "temp": None,
                    "wind": None, "qb_h": None, "qb_a": None})
    return sorted(out, key=lambda r: (r["ts"], r["id"]))
