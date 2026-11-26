"""Pull Kalshi single-game markets (winner / spread / total) and pin each to an ESPN game."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from ..venue.public import _dollars, _ts
from .leagues import LEAGUES, TEAM_TOTAL

ET = ZoneInfo("America/New_York")
_MON = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("st.", "state").replace("saint", "st")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def team_keys(t: dict) -> set:
    return {k for k in (norm(t.get("loc")), norm(t.get("short")), norm(t.get("name")),
                        f"{norm(t.get('loc'))} {norm(t.get('nick'))}".strip(), norm(t.get("abbr"))) if k}


def name_hits(text: str, t: dict) -> bool:
    n = norm(text)
    return any(k == n for k in team_keys(t)) or any(len(k) > 3 and n.startswith(k) for k in team_keys(t))


def event_date(event_ticker: str):
    """KXNFLGAME-26NOV30CARTB -> date(2026, 11, 30)."""
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", event_ticker or "")
    if not m or m.group(2) not in _MON:
        return None
    return datetime(2000 + int(m.group(1)), _MON[m.group(2)], int(m.group(3))).date()


def event_suffix(event_ticker: str) -> str:
    return (event_ticker or "").split("-", 1)[-1]


def _quote(m: dict) -> dict:
    yb, ya = _dollars(m, "yes_bid"), _dollars(m, "yes_ask")
    return {"ticker": m["ticker"], "event": m.get("event_ticker"), "title": m.get("title", ""),
            "sub": m.get("yes_sub_title") or "", "strike": m.get("floor_strike"),
            "yes_bid": float(yb) if yb else None, "yes_ask": float(ya) if ya else None,
            "volume": m.get("volume_fp") or m.get("volume") or 0, "oi": m.get("open_interest_fp") or m.get("open_interest") or 0,
            "close_ts": _ts(m.get("close_time"))}


def fetch_series(public, series: str, max_pages: int = 4) -> list[dict]:
    out, cursor = [], None
    for _ in range(max_pages):
        try:
            ms, cursor = public.markets(status="open", series_ticker=series, limit=1000, cursor=cursor)
        except Exception:
            break
        out += [_quote(m) for m in ms]
        if not cursor:
            break
    return out


def attach(league_key: str, games: list[dict], markets_by_kind: dict) -> dict:
    """Return {espn_game_id: {"winner": [...], "spread": [...], "total": [...]}} with each contract labelled."""
    by_date = {}
    for g in games:
        try:
            d = datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone(ET).date()
        except (AttributeError, ValueError):
            continue
        by_date.setdefault(d, []).append(g)
    suffix_to_game, out = {}, {}
    events = {}
    for q in markets_by_kind.get("winner", []):
        events.setdefault(q["event"], []).append(q)
    for ev, qs in events.items():
        d = event_date(ev)
        for g in by_date.get(d, []):
            sides = {}
            for q in qs:
                if name_hits(q["sub"], g["home"]):
                    sides[q["ticker"]] = "home"
                elif name_hits(q["sub"], g["away"]):
                    sides[q["ticker"]] = "away"
            if len(set(sides.values())) == 2 or (len(qs) == 1 and sides):
                suffix_to_game[event_suffix(ev)] = g["id"]
                slot = out.setdefault(g["id"], {"winner": [], "spread": [], "total": []})
                for q in qs:
                    if q["ticker"] in sides:
                        slot["winner"].append({**q, "kind": "winner", "team": sides[q["ticker"]]})
                break
    gmap = {g["id"]: g for g in games}
    for kind in ("spread", "total"):
        for q in markets_by_kind.get(kind, []):
            gid = suffix_to_game.get(event_suffix(q["event"]))
            if not gid or q["strike"] is None:
                continue
            g = gmap[gid]
            row = {**q, "kind": kind, "line": float(q["strike"])}
            if kind == "spread":
                text = q["sub"] or q["title"]
                if name_hits(text.split(" wins")[0], g["home"]):
                    row["team"] = "home"
                elif name_hits(text.split(" wins")[0], g["away"]):
                    row["team"] = "away"
                else:
                    continue
            out.setdefault(gid, {"winner": [], "spread": [], "total": []})[kind].append(row)
    for q in markets_by_kind.get("team_total", []):
        gid = suffix_to_game.get(event_suffix(q["event"]))
        if not gid or q["strike"] is None:
            continue
        team = team_of(q["sub"] or q["title"], gmap[gid])
        if team:
            out[gid].setdefault("team_total", []).append({**q, "kind": "team_total", "line": float(q["strike"]), "team": team})
    return out


def team_of(text: str, g: dict) -> str | None:
    """'Chicago over 20.5 points scored' -> 'away' when Chicago is the away team."""
    head = re.split(r" over | under | scores| total|:", text or "", maxsplit=1)[0]
    hits = [side for side in ("home", "away") if name_hits(head, g[side])]
    return hits[0] if len(hits) == 1 else None


def all_markets(public, league_key: str) -> dict:
    lg = LEAGUES[league_key]
    out = {kind: fetch_series(public, s) for kind, s in zip(("winner", "spread", "total"), lg.series)}
    if league_key in TEAM_TOTAL:
        out["team_total"] = fetch_series(public, TEAM_TOTAL[league_key])
    return out
