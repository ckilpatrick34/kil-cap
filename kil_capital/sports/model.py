"""Turn ratings + situational factors into a price for each Kalshi contract on a game.

Everything here is our own projection.  The sportsbook line is used afterwards only as
(1) a benchmark shown beside ours, (2) a blend input (books are sharp; see leagues.w_model), and
(3) an agreement check before a trade is suggested."""
from __future__ import annotations

from datetime import datetime, timezone

from .leagues import League
from .ratings import Ratings, norm_cdf


def rest_adj(lg: League, R: Ratings, team_id: str, start_ts: float) -> tuple[float, str | None]:
    last = R.last_played.get(team_id)
    if not last or not start_ts:
        return 0.0, None
    days = (start_ts - last) / 86400
    if lg.b2b_penalty and days < 1.6:
        return -lg.b2b_penalty, "back-to-back"
    return 0.0, None


def football_rest(R: Ratings, home_id: str, away_id: str, start_ts: float) -> tuple[float, str | None]:
    lh, la = R.last_played.get(home_id), R.last_played.get(away_id)
    if not (lh and la and start_ts):
        return 0.0, None
    diff = ((start_ts - lh) - (start_ts - la)) / 86400        # home's extra rest days
    if abs(diff) < 2:
        return 0.0, None
    adj = max(-1.5, min(1.5, 0.25 * diff))
    return adj, f"rest edge {'home' if adj > 0 else 'away'} {abs(diff):.0f}d"


def injury_adj(lg: League, summary: dict, abbr: str, start_ts: float) -> tuple[float, list[str]]:
    """Penalty for players newly ruled Out/Doubtful (last ~10 days).  Long absences are already in the ratings."""
    out, names = 0.0, []
    for team in summary.get("injuries") or []:
        if ((team.get("team") or {}).get("abbreviation") or "").upper() != abbr.upper():
            continue
        for inj in team.get("injuries") or []:
            st = (inj.get("status") or "").lower()
            if st not in ("out", "doubtful"):
                continue
            try:
                ts = datetime.fromisoformat((inj.get("date") or "").replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts = None
            if ts and start_ts and start_ts - ts > 10 * 86400:
                continue
            ath = inj.get("athlete") or {}
            pos = ((ath.get("position") or {}).get("abbreviation") or "").upper()
            names.append(f"{ath.get('displayName', '?')} ({pos}, {st})")
            if lg.key == "nfl":
                out += 4.0 if pos == "QB" else 0.4
            elif lg.key == "cfb":
                out += 3.0 if pos == "QB" else 0.5
            elif lg.key == "nba":
                out += 1.0
            elif lg.key == "cbb":
                out += 0.5
            elif lg.key == "nhl":
                out += 0.25 if pos == "G" else 0.05
    cap = {"nfl": 6, "cfb": 5, "nba": 4, "cbb": 2, "nhl": 0.4}[lg.key]
    return -min(out, cap), names


def weather_adj(wx: dict | None) -> tuple[float, str | None]:
    if not wx:
        return 0.0, None
    adj, why = 0.0, []
    if wx["wind_mph"] >= 15:
        adj -= min(6.0, (wx["wind_mph"] - 12) * 0.35)
        why.append(f"wind {wx['wind_mph']:.0f} mph")
    if wx["precip_mm"] >= 2.5:
        adj -= 2.0
        why.append("heavy rain")
    return adj, (", ".join(why) or None)


def project(lg: League, g: dict, R: Ratings, summary: dict | None = None, wx: dict | None = None) -> dict | None:
    h, a = g["home"]["id"], g["away"]["id"]
    if h not in R.margin or a not in R.margin:
        return None
    notes = []
    m = R.margin[h] - R.margin[a] + (0 if g["neutral"] else lg.hfa)
    if lg.key in ("nfl", "cfb"):
        adj, why = football_rest(R, h, a, g["start_ts"])
        m += adj
        notes += [why] if why else []
    else:
        for side, tid, sign in (("home", h, 1), ("away", a, -1)):
            adj, why = rest_adj(lg, R, tid, g["start_ts"])
            m += sign * adj
            if why:
                notes.append(f"{g[side]['abbr']} {why}")
    inj_names = {}
    if summary:
        for side, sign in (("home", 1), ("away", -1)):
            adj, names = injury_adj(lg, summary, g[side]["abbr"], g["start_ts"])
            m += sign * adj
            if names:
                inj_names[g[side]["abbr"]] = names
    t = 2 * R.base + R.off[h] + R.deff[a] + R.off[a] + R.deff[h]
    if lg.outdoor and not g.get("indoor"):
        adj, why = weather_adj(wx)
        t += adj
        if why:
            notes.append(why)
    gp = min(R.games.get(h, 0), R.games.get(a, 0))
    return {"margin": m, "total": t, "games_played": gp, "notes": notes, "injuries": inj_names,
            "weather": wx, "rating_home": R.margin[h], "rating_away": R.margin[a]}


def devig(ml_a: float | None, ml_b: float | None) -> float | None:
    def imp(x):
        return 100 / (x + 100) if x > 0 else -x / (-x + 100)
    if not ml_a or not ml_b:
        return None
    pa, pb = imp(ml_a), imp(ml_b)
    return pa / (pa + pb)


def book_view(lg: League, odds: dict | None) -> dict:
    """The book's implied home margin / total / home-win probability (vig removed)."""
    if not odds:
        return {}
    out = {}
    if odds.get("spread_home") is not None:
        out["margin"] = -odds["spread_home"]
    if odds.get("total") is not None:
        out["total"] = odds["total"]
    p = devig(odds.get("ml_home"), odds.get("ml_away"))
    if p is not None:
        out["p_home"] = p
    return out


def blend(lg: League, proj: dict, book: dict) -> dict:
    w = lg.w_model
    m = proj["margin"] if "margin" not in book else w * proj["margin"] + (1 - w) * book["margin"]
    t = proj["total"] if "total" not in book else w * proj["total"] + (1 - w) * book["total"]
    return {"margin": m, "total": t}


def p_cover(margin_mean: float, line: float, sigma: float) -> float:
    """P(home margin > line)."""
    return 1 - norm_cdf((line - margin_mean) / sigma)


def p_home_win(lg: League, margin_mean: float) -> float:
    return p_cover(margin_mean, 0.0, lg.sigma_margin)


def p_over(total_mean: float, line: float, sigma: float) -> float:
    return 1 - norm_cdf((line - total_mean) / sigma)


def utcnow_ts() -> float:
    return datetime.now(timezone.utc).timestamp()
