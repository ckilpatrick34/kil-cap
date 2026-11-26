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

NAMES = ["spread", "total", "elo_edge", "m_fast", "m_slow", "pf_h", "pa_h", "pf_a", "pa_a",
         "ats_h", "ats_a", "rest_h", "rest_a", "rest_diff", "div", "dome", "temp", "wind",
         "qb_new_h", "qb_new_a", "n_h", "n_a", "week", "playoff", "neutral"]


def _new(season):
    return {"elo": ELO_MEAN, "mf": 0.0, "ms": 0.0, "pf": 21.0, "pa": 21.0, "ats": 0.0, "qb": None,
            "n": 0, "season": season}


def _ewm(old, new, a):
    return old + a * (new - old)


def build(rows: list[dict]) -> tuple[list[list[float]], list[dict]]:
    """Returns (X, meta). meta[i] has id, season, ts, spread, total, margin, points, home, away."""
    teams: dict[str, dict] = {}
    X, meta = [], []
    for r in rows:
        s = r["season"]
        for t in (r["home"], r["away"]):
            st = teams.setdefault(t, _new(s))
            if st["season"] != s:                     # new season: regress, reset counters
                st.update(elo=ELO_MEAN + (st["elo"] - ELO_MEAN) * 2 / 3, n=0, season=s,
                          mf=st["mf"] * 0.5, ats=st["ats"] * 0.5)
        h, a = teams[r["home"]], teams[r["away"]]
        hfa = 0.0 if r["neutral"] else ELO_HFA
        spread = r["spread"] if r["spread"] is not None else (h["elo"] - a["elo"] + hfa) / 25
        total = r["total"] if r["total"] is not None else h["pf"] + a["pf"]
        rh, ra = r["rest_h"] or 7.0, r["rest_a"] or 7.0
        X.append([spread, total, (h["elo"] - a["elo"] + hfa) / 25, h["mf"] - a["mf"], h["ms"] - a["ms"],
                  h["pf"], h["pa"], a["pf"], a["pa"], h["ats"], a["ats"], rh, ra, rh - ra,
                  float(r["div"]), float(r["dome"]),
                  70.0 if r["dome"] or r["temp"] is None else r["temp"],
                  0.0 if r["dome"] or r["wind"] is None else r["wind"],
                  float(bool(r["qb_h"]) and h["qb"] is not None and r["qb_h"] != h["qb"]),
                  float(bool(r["qb_a"]) and a["qb"] is not None and r["qb_a"] != a["qb"]),
                  float(h["n"]), float(a["n"]), float(r["week"]), float(r["playoff"]), float(r["neutral"])])
        m = r["hs"] - r["as_"]
        meta.append({"id": r["id"], "season": s, "ts": r["ts"], "home": r["home"], "away": r["away"],
                     "spread": r["spread"], "total": r["total"], "margin": m, "points": r["hs"] + r["as_"]})
        # ---- update state with the result (after features were read) ----
        exp = 1 / (1 + 10 ** (-(h["elo"] - a["elo"] + hfa) / 400))
        mult = math.log(abs(m) + 1) * 2.2 / ((h["elo"] - a["elo"] + hfa) * (1 if m > 0 else -1) * 0.001 + 2.2)
        d = ELO_K * mult * ((1.0 if m > 0 else 0.0 if m < 0 else 0.5) - exp)
        h["elo"] += d
        a["elo"] -= d
        for st, mm, pf, pa, ats, qb in ((h, m, r["hs"], r["as_"], m - spread, r["qb_h"]),
                                        (a, -m, r["as_"], r["hs"], -(m - spread), r["qb_a"])):
            mm = max(-28.0, min(28.0, mm))
            st.update(mf=_ewm(st["mf"], mm, FAST), ms=_ewm(st["ms"], mm, SLOW), pf=_ewm(st["pf"], pf, SLOW),
                      pa=_ewm(st["pa"], pa, SLOW), ats=_ewm(st["ats"], ats, SLOW), n=st["n"] + 1,
                      qb=qb or st["qb"])
    return X, meta
