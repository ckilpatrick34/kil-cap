"""ESPN public site API (free, keyless): scoreboards, game summaries (injuries), team results.

Finished days are cached on disk forever; today's and future days are cached for a few minutes."""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from .leagues import League

BASE = "https://site.api.espn.com/apis/site/v2/sports/"


def _f(x):
    try:
        return float(str(x).replace("+", "").replace("o", "").replace("u", ""))
    except (TypeError, ValueError):
        return None


def american(x):
    s = str(x or "").strip().upper()
    if s in ("EVEN", "EV"):
        return 100.0
    return _f(s)


# ESPN conference (group) ids -> short names, per league. Unknown ids show no conference rather than a wrong one.
CONFERENCES = {
    "cfb": {1: "ACC", 151: "American", 4: "Big 12", 5: "Big Ten", 12: "C-USA", 18: "Independent", 15: "MAC",
            17: "Mountain West", 9: "Pac-12", 8: "SEC", 37: "Sun Belt"},
    "cbb": {2: "ACC", 1: "America East", 62: "American", 3: "Atlantic 10", 4: "Big East", 5: "Big Sky",
            6: "Big South", 7: "Big Ten", 8: "Big 12", 9: "Big West", 10: "CAA", 11: "C-USA", 45: "Horizon",
            12: "Ivy", 13: "MAAC", 14: "MAC", 16: "MEAC", 18: "Missouri Valley", 44: "Mountain West", 19: "NEC",
            20: "OVC", 21: "Pac-12", 22: "Patriot", 23: "SEC", 24: "SoCon", 25: "Southland", 26: "SWAC",
            49: "Summit", 27: "Sun Belt", 29: "WCC", 30: "WAC", 46: "ASUN"},
}


def _team(c: dict, league: str = "") -> dict:
    t = c.get("team") or {}
    rec = next((r.get("summary") for r in c.get("records") or [] if r.get("type") == "total"), None)
    rank = (c.get("curatedRank") or {}).get("current")
    cid = t.get("conferenceId") or c.get("conferenceId")
    try:
        conf = CONFERENCES.get(league, {}).get(int(cid)) if cid is not None else None
    except (TypeError, ValueError):
        conf = None
    return {"id": str(t.get("id")), "name": t.get("displayName", ""), "loc": t.get("location", ""),
            "short": t.get("shortDisplayName", ""), "nick": t.get("name", ""), "abbr": t.get("abbreviation", ""),
            "score": _f(c.get("score")), "record": rec, "logo": t.get("logo"),
            "rank": rank if isinstance(rank, int) and 1 <= rank <= 25 else None,   # ESPN uses 99 for unranked
            "conf": conf, "conf_id": str(cid) if cid is not None else None}


def _odds(comp: dict) -> dict | None:
    o = (comp.get("odds") or [None])[0]
    if not o:
        return None

    def pick(node):
        node = node or {}
        return (node.get("close") or {}).get("odds") or (node.get("open") or {}).get("odds")

    ml = o.get("moneyline") or {}
    ps = (o.get("pointSpread") or {}).get("home") or {}
    spread_home = _f((ps.get("close") or {}).get("line") or (ps.get("open") or {}).get("line"))
    if spread_home is None:
        spread_home = _f(o.get("spread"))
    out = {"provider": (o.get("provider") or {}).get("name"), "ml_home": american(pick(ml.get("home"))),
           "ml_away": american(pick(ml.get("away"))), "spread_home": spread_home, "total": _f(o.get("overUnder"))}
    return out if any(v is not None for k, v in out.items() if k != "provider") else None


def parse_event(e: dict, league: str) -> dict | None:
    comp = (e.get("competitions") or [None])[0]
    if not comp:
        return None
    cs = comp.get("competitors") or []
    home = next((c for c in cs if c.get("homeAway") == "home"), None)
    away = next((c for c in cs if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None
    st = (e.get("status") or comp.get("status") or {}).get("type") or {}
    v = comp.get("venue") or {}
    ad = v.get("address") or {}
    start = e.get("date") or comp.get("date")
    try:
        ts = datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        ts = None
    return {"id": str(e.get("id")), "league": league, "name": e.get("shortName") or e.get("name"),
            "start": start, "start_ts": ts, "state": st.get("state", "pre"), "detail": st.get("shortDetail"),
            "neutral": bool(comp.get("neutralSite")), "indoor": v.get("indoor"), "venue": v.get("fullName"),
            "city": ad.get("city"), "region": ad.get("state"), "home": _team(home, league), "away": _team(away, league),
            "odds": _odds(comp)}


class Espn:
    def __init__(self, cache_dir: Path, client: httpx.Client | None = None, req_per_sec: float = 4.0):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.http = client or httpx.Client(timeout=20, headers={"User-Agent": "kil-capital-terminal"})
        self._gap, self._last, self._lock = 1.0 / req_per_sec, 0.0, threading.Lock()
        self._mem: dict = {}
        self.last_error: str | None = None

    def _get(self, url: str, params: dict | None = None) -> dict:
        with self._lock:
            w = self._gap - (time.time() - self._last)
            if w > 0:
                time.sleep(w)
            self._last = time.time()
        r = self.http.get(url, params=params)
        r.raise_for_status()
        return r.json()

    def scoreboard(self, lg: League, day: date, ttl: float = 120) -> list[dict]:
        key = f"{lg.key}-{day:%Y%m%d}"
        f = self.dir / f"{key}.json"
        past = day < (datetime.now(timezone.utc) - timedelta(hours=36)).date()
        if past and f.exists():
            return json.loads(f.read_text())
        hit = self._mem.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        p = {"dates": f"{day:%Y%m%d}", "limit": 400}
        if lg.groups:
            p["groups"] = lg.groups
        try:
            data = self._get(BASE + lg.path + "/scoreboard", p)
        except Exception as e:
            self.last_error = f"{lg.key} {day}: {e}"
            return hit[1] if hit else []
        games = [g for g in (parse_event(e, lg.key) for e in data.get("events") or []) if g]
        self._mem[key] = (time.time(), games)
        if past and all(g["state"] == "post" for g in games):
            f.write_text(json.dumps(games))
        return games

    def history(self, lg: League, today: date) -> list[dict]:
        d, out = date.fromisoformat(lg.season_start), []
        while d < today:
            out += [g for g in self.scoreboard(lg, d) if g["state"] == "post"]
            d += timedelta(days=1)
        return out

    def summary(self, lg: League, event_id: str, ttl: float = 900) -> dict:
        key = f"sum-{lg.key}-{event_id}"
        hit = self._mem.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        try:
            d = self._get(BASE + lg.path + "/summary", {"event": event_id})
        except Exception as e:
            self.last_error = f"summary {event_id}: {e}"
            return hit[1] if hit else {}
        keep = {"injuries": d.get("injuries") or [], "predictor": d.get("predictor") or {}}
        self._mem[key] = (time.time(), keep)
        return keep
