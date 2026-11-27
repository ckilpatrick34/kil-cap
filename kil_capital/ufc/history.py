"""Turn ufcstats.com history into one pre-fight feature row per bout, using only fights that came before it.

Source: the public scrape at github.com/Greco1899/scrape_ufc_stats (refreshed weekly from ufcstats.com):
event dates, results, per-round striking/grappling stats and fighter height/reach/DOB.
Every number on a row is known before the fight starts, so walk-forward tests are honest.
"""
from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

RAW_BASE = "https://raw.githubusercontent.com/Greco1899/scrape_ufc_stats/main/"
FILES = ("ufc_event_details.csv", "ufc_fight_results.csv", "ufc_fight_stats.csv", "ufc_fighter_tott.csv")


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]+", " ", s).strip()


def _of(x: str) -> tuple[float, float]:
    """'11 of 25' -> (11, 25)."""
    m = re.match(r"\s*(\d+)\s+of\s+(\d+)", x or "")
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


def _secs(x: str) -> float:
    m = re.match(r"\s*(\d+):(\d+)", x or "")
    return float(m.group(1)) * 60 + float(m.group(2)) if m else 0.0


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _inches(x: str) -> float | None:
    m = re.match(r"\s*(\d+)'\s*(\d+)", x or "")
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    m = re.match(r"\s*(\d+(?:\.\d+)?)\"", x or "")
    return float(m.group(1)) if m else None


def _dob(x: str) -> date | None:
    try:
        return datetime.strptime((x or "").strip(), "%b %d, %Y").date()
    except ValueError:
        return None


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def load_bouts(raw: Path) -> tuple[list[dict], dict]:
    """Chronological bouts: {date, a, b, winner (a|b|None), method, rounds, secs, title5, stats{a,b}, wc}."""
    ev_date = {}
    for r in read_csv(raw / "ufc_event_details.csv"):
        try:
            ev_date[r["EVENT"]] = datetime.strptime(r["DATE"], "%B %d, %Y").date()
        except (KeyError, ValueError):
            pass
    stats = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for r in read_csv(raw / "ufc_fight_stats.csv"):
        if not r.get("FIGHTER"):
            continue
        s = stats[(r["EVENT"], r["BOUT"])][norm(r["FIGHTER"])]
        for k in ("SIG.STR.", "TD", "TOTAL STR.", "HEAD", "BODY", "LEG", "DISTANCE", "CLINCH", "GROUND"):
            l, a = _of(r.get(k))
            s[k + "_l"] += l
            s[k + "_a"] += a
        s["KD"] += _num(r.get("KD"))
        s["SUB"] += _num(r.get("SUB.ATT"))
        s["CTRL"] += _secs(r.get("CTRL"))
    tott = {}
    for r in read_csv(raw / "ufc_fighter_tott.csv"):
        tott.setdefault(norm(r["FIGHTER"]), {"reach": _inches(r.get("REACH")), "height": _inches(r.get("HEIGHT")),
                                             "dob": _dob(r.get("DOB")), "stance": (r.get("STANCE") or "").lower()})
    bouts = []
    for r in read_csv(raw / "ufc_fight_results.csv"):
        d = ev_date.get(r["EVENT"])
        parts = re.split(r"\s+vs\.?\s+", r["BOUT"].strip(), maxsplit=1)
        if d is None or len(parts) != 2:
            continue
        a, b = norm(parts[0]), norm(parts[1])
        out = r.get("OUTCOME", "")
        winner = "a" if out.startswith("W/") else "b" if out.startswith("L/") else None
        rnd = int(_num(r.get("ROUND")) or 1)
        secs = (rnd - 1) * 300 + _secs(r.get("TIME"))
        st = stats.get((r["EVENT"], r["BOUT"]), {})
        bouts.append({"date": d, "a": a, "b": b, "a_name": parts[0].strip(), "b_name": parts[1].strip(),
                      "winner": winner, "method": r.get("METHOD", ""), "round": rnd, "secs": secs,
                      "five": (r.get("TIME FORMAT") or "").startswith("5 Rnd"), "wc": r.get("WEIGHTCLASS", ""),
                      "event": r["EVENT"], "stats": {"a": dict(st.get(a, {})), "b": dict(st.get(b, {}))}})
    bouts.sort(key=lambda x: x["date"])   # same-day order does not matter: rows read state before the day's updates
    return bouts, tott


@dataclass
class Fighter:
    elo: float = 1500.0
    n: int = 0
    wins: int = 0
    losses: int = 0
    ko_wins: int = 0
    sub_wins: int = 0
    ko_losses: int = 0
    last: date | None = None
    recent: list = field(default_factory=list)   # 1 win, 0 loss, newest last
    recent_diff: list = field(default_factory=list)   # sig strikes landed minus absorbed per minute, last 3 fights
    opp_elo: list = field(default_factory=list)       # pre-fight Elo of each opponent
    secs: float = 0.0
    tot: dict = field(default_factory=lambda: defaultdict(float))   # career totals for and against


ELO_K, ELO_FINISH = 70.0, 1.15   # tuned on 2005-2014 fights only (see research/ufc_model.py)
FEATURES = ("elo", "exp", "winpct", "form3", "layoff", "age", "reach", "height", "slpm", "sapm", "str_acc",
            "str_def", "td15", "td_acc", "td_def", "sub15", "kd15", "ctrl", "ko_loss", "finish", "debut",
            "southpaw", "age_over", "recent_str", "opp_q")


def _rate(x, secs, per=60.0, prior=0.0, prior_secs=600.0):
    """Per-minute (or per-15) rate shrunk toward a prior with ~2 rounds of pseudo-time, so debutants are sane."""
    return (x + prior * prior_secs / per) / ((secs + prior_secs) / per)


def _pct(made, att, prior, k=10.0):
    return (made + prior * k) / (att + k)


PRIORS = {"slpm": 3.5, "sapm": 3.5, "td15": 1.3, "sub15": 0.5, "kd15": 0.25, "str_acc": 0.45, "str_def": 0.55,
          "td_acc": 0.35, "td_def": 0.65, "ctrl": 0.15}


def profile(f: Fighter, info: dict, on: date) -> dict:
    t, s = f.tot, f.secs
    age = ((on - info["dob"]).days / 365.25) if info.get("dob") else None
    return {
        "elo": f.elo, "exp": math.log1p(f.n), "winpct": (f.wins + 1) / (f.n + 2),
        "form3": (sum(f.recent[-3:]) + 1.5) / (len(f.recent[-3:]) + 3),
        "layoff": min((on - f.last).days, 1500) / 365.0 if f.last else 1.0,
        "age": age, "reach": info.get("reach"), "height": info.get("height"),
        "slpm": _rate(t["sig_l"], s, 60, PRIORS["slpm"]), "sapm": _rate(t["opp_sig_l"], s, 60, PRIORS["sapm"]),
        "str_acc": _pct(t["sig_l"], t["sig_a"], PRIORS["str_acc"], 40),
        "str_def": 1 - _pct(t["opp_sig_l"], t["opp_sig_a"], 1 - PRIORS["str_def"], 40),
        "td15": _rate(t["td_l"], s, 900, PRIORS["td15"]), "td_acc": _pct(t["td_l"], t["td_a"], PRIORS["td_acc"]),
        "td_def": 1 - _pct(t["opp_td_l"], t["opp_td_a"], 1 - PRIORS["td_def"]),
        "sub15": _rate(t["sub"], s, 900, PRIORS["sub15"]), "kd15": _rate(t["kd"], s, 900, PRIORS["kd15"]),
        "ctrl": (t["ctrl"] - t["opp_ctrl"]) / (s + 600.0),   # net share of fight time spent in control
        "ko_loss": (f.ko_losses + 0.2) / (f.n + 2), "finish": (f.ko_wins + f.sub_wins + 1) / (f.wins + 2),
        "debut": 1.0 if f.n == 0 else 0.0, "southpaw": 1.0 if info.get("stance") == "southpaw" else 0.0,
        "age_over": max((age or 29.5) - 32.0, 0.0),
        "recent_str": sum(f.recent_diff[-3:]) / (len(f.recent_diff[-3:]) + 1),
        "opp_q": (sum(f.opp_elo[-5:]) + 1500 * 2) / (len(f.opp_elo[-5:]) + 2) / 400.0,
    }


MEANS = {"age": 29.5, "reach": 72.0, "height": 70.0}


def diff_row(pa: dict, pb: dict) -> list[float]:
    """A-minus-B feature vector. Missing body measurements count as the league average."""
    row = []
    for k in FEATURES:
        va, vb = pa.get(k), pb.get(k)
        va = MEANS.get(k, 0.0) if va is None else va
        vb = MEANS.get(k, 0.0) if vb is None else vb
        row.append((va - vb) / (400.0 if k == "elo" else 1.0))
    return row


def _update(f: Fighter, me: dict, opp: dict, secs: float):
    t = f.tot
    t["sig_l"] += me.get("SIG.STR._l", 0)
    t["sig_a"] += me.get("SIG.STR._a", 0)
    t["opp_sig_l"] += opp.get("SIG.STR._l", 0)
    t["opp_sig_a"] += opp.get("SIG.STR._a", 0)
    t["td_l"] += me.get("TD_l", 0)
    t["td_a"] += me.get("TD_a", 0)
    t["opp_td_l"] += opp.get("TD_l", 0)
    t["opp_td_a"] += opp.get("TD_a", 0)
    t["sub"] += me.get("SUB", 0)
    t["kd"] += me.get("KD", 0)
    t["ctrl"] += me.get("CTRL", 0)
    t["opp_ctrl"] += opp.get("CTRL", 0)
    f.secs += secs if (me or opp) else 0.0   # only count time we have stats for, so rates stay consistent


def walk(bouts: list[dict], tott: dict, k: float = ELO_K, finish_mult: float = ELO_FINISH):
    """Yield (bout, profile_a, profile_b) before each fight, then update both fighters. Returns final states."""
    fighters: dict[str, Fighter] = defaultdict(Fighter)
    rows = []
    i = 0
    while i < len(bouts):
        day = bouts[i]["date"]
        j = i
        while j < len(bouts) and bouts[j]["date"] == day:
            j += 1
        todays = bouts[i:j]
        for bt in todays:
            fa, fb = fighters[bt["a"]], fighters[bt["b"]]
            rows.append((bt, profile(fa, tott.get(bt["a"], {}), day), profile(fb, tott.get(bt["b"], {}), day)))
        for bt in todays:
            fa, fb = fighters[bt["a"]], fighters[bt["b"]]
            fa.opp_elo = (fa.opp_elo + [fb.elo])[-5:]
            fb.opp_elo = (fb.opp_elo + [fa.elo])[-5:]
            sa_, sb_ = bt["stats"]["a"], bt["stats"]["b"]
            if (sa_ or sb_) and bt["secs"] > 0:
                d = (sa_.get("SIG.STR._l", 0) - sb_.get("SIG.STR._l", 0)) / (bt["secs"] / 60)
                fa.recent_diff = (fa.recent_diff + [d])[-3:]
                fb.recent_diff = (fb.recent_diff + [-d])[-3:]
            if bt["winner"] is not None:
                ea = 1 / (1 + 10 ** ((fb.elo - fa.elo) / 400))
                sa = 1.0 if bt["winner"] == "a" else 0.0
                fin = bt["method"].startswith(("KO", "TKO", "Submission"))
                kk = k * (finish_mult if fin else 1.0) * (1.0 if min(fa.n, fb.n) >= 3 else 1.2)
                fa.elo += kk * (sa - ea)
                fb.elo -= kk * (sa - ea)
                for f, won in ((fa, sa == 1.0), (fb, sa == 0.0)):
                    f.wins += won
                    f.losses += not won
                    f.recent = (f.recent + [1 if won else 0])[-5:]
                w, l = (fa, fb) if sa == 1.0 else (fb, fa)
                if bt["method"].startswith(("KO", "TKO")):
                    w.ko_wins += 1
                    l.ko_losses += 1
                elif bt["method"].startswith("Submission"):
                    w.sub_wins += 1
            for f in (fa, fb):
                f.n += 1
                f.last = day
            _update(fa, bt["stats"]["a"], bt["stats"]["b"], bt["secs"])
            _update(fb, bt["stats"]["b"], bt["stats"]["a"], bt["secs"])
        i = j
    return rows, fighters
