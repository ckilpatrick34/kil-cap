"""Independent team ratings fitted on this season's results only (no betting lines used).

Margin model (Massey / ridge):   home_pts - away_pts = r_home - r_away + hfa*(not neutral) + noise
Scoring model (off/def ridge):  team_pts = base + off_team + def_opponent + hfa/2*(home & not neutral)
Recent games weigh more (exponential half-life); blowouts are capped so garbage time doesn't dominate.
Pure Python Gauss-Seidel - a season is a few thousand games at most."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .leagues import League


@dataclass
class Ratings:
    margin: dict = field(default_factory=dict)   # team_id -> points better than average
    off: dict = field(default_factory=dict)
    deff: dict = field(default_factory=dict)
    base: float = 0.0                             # average points per team per game
    games: dict = field(default_factory=dict)     # team_id -> games played
    last_played: dict = field(default_factory=dict)  # team_id -> last game start_ts
    n: int = 0


def fit(lg: League, games: list[dict], now_ts: float, lam: float = 2.0, iters: int = 60,
        lam_total: float | None = None) -> Ratings:
    lam_t = lg.lam_total if lam_total is None else lam_total   # scoring ratings need far more shrinkage than margin
    rows = []
    for g in games:
        hs, as_ = g["home"]["score"], g["away"]["score"]
        if hs is None or as_ is None or g.get("start_ts") is None:
            continue
        age = max(0.0, (now_ts - g["start_ts"]) / 86400)
        w = 0.5 ** (age / lg.halflife_days)
        rows.append((g["home"]["id"], g["away"]["id"], hs, as_, 0.0 if g["neutral"] else 1.0, w, g["start_ts"]))
    R = Ratings(n=len(rows))
    if not rows:
        return R
    teams = {t for r in rows for t in r[:2]}
    for h, a, *_r, ts in rows:
        for t in (h, a):
            R.games[t] = R.games.get(t, 0) + 1
            R.last_played[t] = max(R.last_played.get(t, 0), ts)
    by_team = {t: [] for t in teams}
    for i, r in enumerate(rows):
        by_team[r[0]].append(i)
        by_team[r[1]].append(i)
    cap = lg.blowout_cap
    r_ = {t: 0.0 for t in teams}
    for _ in range(iters):
        for t in teams:
            num = den = 0.0
            for i in by_team[t]:
                h, a, hs, as_, home, w, _ts = rows[i]
                m = max(-cap, min(cap, hs - as_)) - lg.hfa * home
                if t == h:
                    num += w * (m + r_[a])
                else:
                    num += w * (-m + r_[h])
                den += w
            r_[t] = num / (den + lam)
        mean = sum(r_.values()) / len(r_)
        r_ = {t: v - mean for t, v in r_.items()}
    R.margin = r_
    wsum = sum(r[5] for r in rows)
    R.base = sum(r[5] * (r[2] + r[3]) / 2 for r in rows) / wsum
    o = {t: 0.0 for t in teams}
    d = {t: 0.0 for t in teams}
    for _ in range(iters):
        for t in teams:
            no = nd = den = 0.0
            for i in by_team[t]:
                h, a, hs, as_, home, w, _ts = rows[i]
                if t == h:
                    no += w * (hs - R.base - lg.hfa / 2 * home - d[a])
                    nd += w * (as_ - R.base + lg.hfa / 2 * home - o[a])
                else:
                    no += w * (as_ - R.base + lg.hfa / 2 * home - d[h])
                    nd += w * (hs - R.base - lg.hfa / 2 * home - o[h])
                den += w
            o[t], d[t] = no / (den + lam_t), nd / (den + lam_t)
    R.off, R.deff = o, d
    return R


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
