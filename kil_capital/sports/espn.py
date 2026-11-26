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


def _team(c: dict) -> dict:
    t = c.get("team") or {}
    rec = next((r.get("summary") for r in c.get("records") or [] if r.get("type") == "total"), None)
    return {"id": str(t.get("id")), "name": t.get("displayName", ""), "loc": t.get("location", ""),
            "short": t.get("shortDisplayName", ""), "nick": t.get("name", ""), "abbr": t.get("abbreviation", ""),
            "score": _f(c.get("score")), "record": rec, "logo": t.get("logo")}


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
            "city": ad.get("city"), "region": ad.get("state"), "home": _team(home), "away": _team(away),
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
