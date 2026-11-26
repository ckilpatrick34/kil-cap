"""Public multi-season histories with closing lines, adapted to the common row schema in history.py.

Extra row fields used here (all optional, None when a source lacks them):
    ml_h, ml_a           closing American moneylines
    spread_open, total_open   opening lines (spread in the same home-margin convention)
    tot_odds             closing price of the OVER (American); under is mirrored with a 4.5% hold

Sources (reachable from the cloud through anonymous git reads of public GitHub repos):
  * flancast90/sportsbookreview-scraper  data/{nba,nhl,mlb}_archive_10Y.json  (SBR, seasons 2011-2021)
  * sportsdataverse/cfbfastR-data        betting/csv/cfb_line_odds.csv.gz + cfb/schedules (2006-2022)
Downloaded once into data/raw/ by `fetch()`; never committed."""
from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SBR_REPO = "https://github.com/flancast90/sportsbookreview-scraper"
CFB_REPO = "https://github.com/sportsdataverse/cfbfastR-data"

ALIAS = {
    "nba": {"NewJersey": "Nets", "Golden State": "Warriors", "LA Clippers": "Clippers", "Oklahoma City": "Thunder"},
    "nhl": {"Phoenix": "Coyotes", "Arizonas": "Coyotes", "SeattleKraken": "Kraken", "NY Islanders": "Islanders",
            "Tampa": "Lightning", "Tampa Bay": "Lightning", "WinnipegJets": "Jets"},
    "mlb": {"LOS": "Dodgers", "CUB": "Cubs", "KAN": "Royals", "SDG": "Padres", "SFO": "Giants", "SFG": "Giants",
            "TAM": "Rays", "BRS": "Red Sox"},
}


def _sparse(repo: str, dest: Path, paths: list[str]) -> Path:
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", repo, str(dest)],
                       check=True, env={"GIT_LFS_SKIP_SMUDGE": "1", "PATH": "/usr/bin:/bin:/usr/local/bin"})
    subprocess.run(["git", "-C", str(dest), "checkout", "-q", "HEAD", "--", *paths], check=True)
    return dest


def _f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _ml_ok(h, a):
    """Both prices present and the pair implies a sane bookmaker hold (0-12%)."""
    if not h or not a:
        return False
    s = implied(h) + implied(a)
    return 1.0 <= s <= 1.12


def implied(ml: float) -> float:
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def payout(ml: float) -> float:
    """Profit per 1 unit staked at American odds."""
    return ml / 100 if ml > 0 else 100 / -ml


def under_price(over: float, hold: float = 0.045) -> float:
    p = min(max(1 + hold - implied(over), 0.05), 0.95)
    return -100 * p / (1 - p) if p > 0.5 else 100 * (1 - p) / p


def _ts(yyyymmdd) -> float:
    d = str(int(float(yyyymmdd)))
    return datetime(int(d[:4]), int(d[4:6]), int(d[6:]), tzinfo=timezone.utc).timestamp()


def _base(league, season, ts, home, away, hs, as_, gid):
    return {"id": gid, "league": league, "season": season, "ts": ts, "week": 0, "playoff": False,
            "home": home, "away": away, "hs": hs, "as_": as_, "neutral": False, "spread": None, "total": None,
            "rest_h": None, "rest_a": None, "div": False, "dome": False, "temp": None, "wind": None,
            "qb_h": None, "qb_a": None, "ml_h": None, "ml_a": None, "spread_open": None, "total_open": None,
            "tot_odds": None}


def sbr(league: str, raw_dir: Path) -> list[dict]:
    repo = _sparse(SBR_REPO, Path(raw_dir) / "sbr", [f"data/{league}_archive_10Y.json"])
    data = json.loads((repo / f"data/{league}_archive_10Y.json").read_text())
    al = ALIAS.get(league, {})
    names = Counter(al.get(str(t), str(t)) for g in data for t in (g["home_team"], g["away_team"]))
    out = []
    for i, g in enumerate(data):
        h, a = al.get(str(g["home_team"]), str(g["home_team"])), al.get(str(g["away_team"]), str(g["away_team"]))
        hs, as_ = _f(g.get("home_final")), _f(g.get("away_final"))
        if hs is None or as_ is None or names[h] < 200 or names[a] < 200 or h == a or not g.get("date"):
            continue
        r = _base(league, int(g["season"]), _ts(g["date"]), h, a, hs, as_, f"{league}{int(g['date'])}{h}{a}")
        mh, ma = _f(g.get("home_close_ml")), _f(g.get("away_close_ml"))
        if _ml_ok(mh, ma):
            r["ml_h"], r["ml_a"] = mh, ma
        tot = _f(g.get("close_over_under"))
        if tot and tot > (150 if league == "nba" else 3):
            r["total"] = tot
            r["total_open"] = _f(g.get("open_over_under")) or tot
            r["tot_odds"] = _f(g.get("close_over_under_odds")) or None
        if league == "nba":
            sp = _f(g.get("home_close_spread"))
            if sp is not None and abs(sp) < 30 and (sp != 0 or r["ml_h"]):
                r["spread"] = -sp
                op = _f(g.get("home_open_spread"))
                r["spread_open"] = -op if op is not None and abs(op) < 30 else r["spread"]
        out.append(r)
    out.sort(key=lambda r: (r["ts"], r["id"]))
    # SBR lists some doubleheaders/duplicates twice: keep the first of identical (date, home, away)
    seen, uniq = set(), []
    for r in out:
        if r["id"] not in seen:
            seen.add(r["id"])
            uniq.append(r)
    return uniq


def cfb(raw_dir: Path) -> list[dict]:
    import glob

    import pandas as pd
    repo = _sparse(CFB_REPO, Path(raw_dir) / "cfbfastR", ["betting/csv/cfb_line_odds.csv.gz", "cfb/schedules/parquet"])
    sched = []
    for f in sorted(glob.glob(str(repo / "cfb/schedules/parquet/*.parquet"))):
        t = pd.read_parquet(f)
        if "game_id" in t:
            sched.append(t[["game_id", "season", "start_date", "neutral_site", "home_id", "away_id", "home_score",
                            "away_score", "season_type", "week", "venue_indoor"]])
    s = pd.concat(sched)
    s["game_id"] = s.game_id.astype("int64")
    lines = pd.read_csv(repo / "betting/csv/cfb_line_odds.csv.gz")
    lines = lines[lines.game_id.notna()].copy()
    lines["game_id"] = lines.game_id.astype("int64")
    # Map each betting abbreviation to the ESPN team id it co-occurs with most (abbr order is not reliable).
    ids = s.set_index("game_id")[["home_id", "away_id"]]
    pairs = lines[["game_id", "abbr"]].drop_duplicates().join(ids, on="game_id").dropna()
    votes = Counter()
    for _, p in pairs.iterrows():
        votes[(p.abbr, int(p.home_id))] += 1
        votes[(p.abbr, int(p.away_id))] += 1
    best = {}
    for (ab, tid), n in votes.items():
        if n > best.get(ab, (None, 0))[1]:
            best[ab] = (tid, n)
    lines["tid"] = lines.abbr.map(lambda x: best.get(x, (None,))[0])
    lines = lines.join(ids, on="game_id")
    lines["is_home"] = lines.tid == lines.home_id
    lines["is_away"] = lines.tid == lines.away_id

    def med(df):
        return float(df.median()) if len(df) else None

    agg = {}
    for gid, g in lines.groupby("game_id"):
        sp = g[(g.market_type == "spread") & g.is_home].lines.dropna()
        spo = g[(g.market_type == "spread") & g.is_home].opening_lines.dropna()
        tot = g[g.market_type == "total"].lines.dropna()
        toto = g[g.market_type == "total"].opening_lines.dropna()
        mh = g[(g.market_type == "money_line") & g.is_home].odds.dropna()
        ma = g[(g.market_type == "money_line") & g.is_away].odds.dropna()
        agg[gid] = {"spread": -med(sp) if len(sp) else None, "spread_open": -med(spo) if len(spo) else None,
                    "total": med(tot[tot > 20]), "total_open": med(toto[toto > 20]),
                    "ml_h": med(mh), "ml_a": med(ma)}
    out = []
    for g in s.itertuples():
        hs, as_ = _f(g.home_score), _f(g.away_score)
        if hs is None or as_ is None or g.start_date is None:
            continue
        ts = pd.Timestamp(g.start_date).timestamp()
        r = _base("cfb", int(g.season), ts, str(g.home_id), str(g.away_id), hs, as_, str(g.game_id))
        r.update(neutral=bool(g.neutral_site), playoff=str(g.season_type) not in ("2", "regular"),
                 week=int(_f(g.week) or 0), dome=bool(g.venue_indoor))
        a = agg.get(g.game_id)
        if a:
            if a["spread"] is not None and abs(a["spread"]) < 60:
                r["spread"], r["spread_open"] = a["spread"], a["spread_open"] if a["spread_open"] is not None else a["spread"]
            if a["total"]:
                r["total"], r["total_open"] = a["total"], a["total_open"] or a["total"]
            if _ml_ok(a["ml_h"], a["ml_a"]):
                r["ml_h"], r["ml_a"] = a["ml_h"], a["ml_a"]
        out.append(r)
    return sorted(out, key=lambda r: (r["ts"], r["id"]))
