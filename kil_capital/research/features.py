"""Point-in-time features: every feature for a game is computed only from games that finished before it.

Games are streamed in date order; a game's features are read from the running team state, then the
state is updated with its result. That makes leakage structurally impossible (tested).

Per team we compress the whole history into a handful of numbers:
  Elo (margin-aware, regressed 1/3 to the mean each season), fast and slow EWMAs of margin,
  points for/against, and "market error" (how much the team beat the closing spread),
  starting QB and games played this season."""
from __future__ import annotations

import math

FAST, SLOW = 0.30, 0.08
ELO_K, ELO_HFA, ELO_MEAN = 20.0, 48.0, 1500.0

# Per-league feature settings. "scale" = Elo points per point of margin; "clip" caps a blowout's
# weight; "pf0" = a new team's points per game; "regress" = share of Elo kept across seasons.
# NFL values are the originals. tune() in deep.py searches around these on selection seasons only.
LEAGUES = {
    "nfl": dict(k=20.0, hfa=48.0, scale=25.0, clip=28.0, pf0=21.0, fast=FAST, slow=SLOW, regress=2 / 3, rest0=7.0),
    "cfb": dict(k=25.0, hfa=55.0, scale=25.0, clip=35.0, pf0=28.0, fast=FAST, slow=SLOW, regress=0.6, rest0=7.0),
    "nba": dict(k=20.0, hfa=90.0, scale=28.0, clip=30.0, pf0=105.0, fast=0.15, slow=0.04, regress=0.75, rest0=2.0),
    "nhl": dict(k=6.0, hfa=30.0, scale=150.0, clip=4.0, pf0=2.9, fast=0.10, slow=0.03, regress=0.7, rest0=2.0),
    "mlb": dict(k=4.0, hfa=24.0, scale=150.0, clip=6.0, pf0=4.4, fast=0.10, slow=0.02, regress=0.7, rest0=1.0),
}

NAMES = ["spread", "total", "elo_edge", "m_fast", "m_slow", "pf_h", "pa_h", "pf_a", "pa_a",
         "ats_h", "ats_a", "rest_h", "rest_a", "rest_diff", "div", "dome", "temp", "wind",
         "qb_new_h", "qb_new_a", "n_h", "n_a", "week", "playoff", "neutral", "mkt_p"]


def devig(ml_h, ml_a):
    """Closing moneylines -> home win probability with the bookmaker's margin removed (or None)."""
    if not ml_h or not ml_a:
        return None
    ph = 100 / (ml_h + 100) if ml_h > 0 else -ml_h / (-ml_h + 100)
    pa = 100 / (ml_a + 100) if ml_a > 0 else -ml_a / (-ml_a + 100)
    return ph / (ph + pa)


def _new(season, pf0=21.0):
    return {"elo": ELO_MEAN, "mf": 0.0, "ms": 0.0, "pf": pf0, "pa": pf0, "ats": 0.0, "qb": None,
            "n": 0, "season": season, "last": None}


def _ewm(old, new, a):
    return old + a * (new - old)


def _rest(st, ts, default):
    """Days since the team's previous game this season (capped at 10); default when it's the opener."""
    return default if st["last"] is None else min(10.0, (ts - st["last"]) / 86400)


def build(rows: list[dict], cfg: dict | None = None) -> tuple[list[list[float]], list[dict]]:
    """Returns (X, meta). meta[i] has id, season, ts, spread, total, margin, points, home, away, ml_h, ml_a."""
    c = cfg or LEAGUES["nfl"]
    K, HFA, SC, CL, FA, SL = c["k"], c["hfa"], c["scale"], c["clip"], c["fast"], c["slow"]
    teams: dict[str, dict] = {}
    X, meta = [], []
    for r in rows:
        s = r["season"]
        for t in (r["home"], r["away"]):
            st = teams.setdefault(t, _new(s, c["pf0"]))
            if st["season"] != s:                     # new season: regress, reset counters
                st.update(elo=ELO_MEAN + (st["elo"] - ELO_MEAN) * c["regress"], n=0, season=s,
                          mf=st["mf"] * 0.5, ats=st["ats"] * 0.5, last=None)
        h, a = teams[r["home"]], teams[r["away"]]
        hfa = 0.0 if r["neutral"] else HFA
        elo_p = 1 / (1 + 10 ** (-(h["elo"] - a["elo"] + hfa) / 400))
        spread = r["spread"] if r["spread"] is not None else (h["elo"] - a["elo"] + hfa) / SC
        total = r["total"] if r["total"] is not None else h["pf"] + a["pf"]
        rh = r["rest_h"] or _rest(h, r["ts"], c["rest0"])
        ra = r["rest_a"] or _rest(a, r["ts"], c["rest0"])
        mp = devig(r.get("ml_h"), r.get("ml_a"))
        X.append([spread, total, (h["elo"] - a["elo"] + hfa) / SC, h["mf"] - a["mf"], h["ms"] - a["ms"],
                  h["pf"], h["pa"], a["pf"], a["pa"], h["ats"], a["ats"], rh, ra, rh - ra,
                  float(r["div"]), float(r["dome"]),
                  70.0 if r["dome"] or r["temp"] is None else r["temp"],
                  0.0 if r["dome"] or r["wind"] is None else r["wind"],
                  float(bool(r["qb_h"]) and h["qb"] is not None and r["qb_h"] != h["qb"]),
                  float(bool(r["qb_a"]) and a["qb"] is not None and r["qb_a"] != a["qb"]),
                  float(h["n"]), float(a["n"]), float(r["week"]), float(r["playoff"]), float(r["neutral"]),
                  mp if mp is not None else elo_p])
        m = r["hs"] - r["as_"]
        meta.append({"id": r["id"], "season": s, "ts": r["ts"], "home": r["home"], "away": r["away"],
                     "spread": r["spread"], "total": r["total"], "margin": m, "points": r["hs"] + r["as_"],
                     "ml_h": r.get("ml_h"), "ml_a": r.get("ml_a"), "mkt_p": mp})
        # ---- update state with the result (after features were read) ----
        exp = elo_p
        mult = math.log(abs(m) + 1) * 2.2 / ((h["elo"] - a["elo"] + hfa) * (1 if m > 0 else -1) * 0.001 + 2.2)
        d = K * mult * ((1.0 if m > 0 else 0.0 if m < 0 else 0.5) - exp)
        h["elo"] += d
        a["elo"] -= d
        for st, mm, pf, pa, ats, qb in ((h, m, r["hs"], r["as_"], m - spread, r["qb_h"]),
                                        (a, -m, r["as_"], r["hs"], -(m - spread), r["qb_a"])):
            mm = max(-CL, min(CL, mm))
            st.update(mf=_ewm(st["mf"], mm, FA), ms=_ewm(st["ms"], mm, SL), pf=_ewm(st["pf"], pf, SL),
                      pa=_ewm(st["pa"], pa, SL), ats=_ewm(st["ats"], ats, SL), n=st["n"] + 1,
                      qb=qb or st["qb"], last=r["ts"])
    return X, meta
