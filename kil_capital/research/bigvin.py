"""Learn from Big Vin's graded history: why it loses, which segments win, and the honest 60% search.

    python -m kil_capital.research.bigvin [data/bigvin]      (run on the Mac; the site blocks the cloud)

Reads every .json / .csv under the folder, maps whatever column names it finds onto
league / bet type / price / edge / result / date / line movement, then writes:
  * data/bigvin_picks.json        normalised picks; the nightly learner folds them into segments.json
  * reports/BIG_VIN_LEARNING.md   loss analysis by league, bet type, edge, fav/dog, line move, confidence
                                  rank, plus the 60% win-rate search with out-of-sample ROI
If a column can't be mapped it prints the columns it saw, so the alias lists below can be extended."""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ..config import ROOT
from ..sports import segments as SEG

ALIASES = {
    "league": ("league", "sport", "sport_key", "sportkey", "competition"),
    "kind": ("kind", "bet_type", "bettype", "market", "type", "pick_type", "wager_type"),
    "odds": ("odds", "american_odds", "price", "line_odds", "book_odds", "juice"),
    "prob": ("implied_prob", "implied", "market_prob", "price_prob"),
    "edge": ("edge", "model_edge", "ev", "expected_value", "value"),
    "result": ("result", "outcome", "status", "grade", "win", "won"),
    "ts": ("ts", "date", "game_date", "commence_time", "start", "start_time", "event_date"),
    "open": ("open_line", "opening_line", "line_open", "open"),
    "close": ("close_line", "closing_line", "line_close", "close"),
    "clv": ("clv", "closing_line_value"),
    "rank": ("rank", "confidence_rank", "pick_rank", "position"),
}
LEAGUE_MAP = {"ncaaf": "cfb", "cfb": "cfb", "college football": "cfb", "ncaab": "cbb", "ncaam": "cbb",
              "cbb": "cbb", "college basketball": "cbb", "nfl": "nfl", "nba": "nba", "nhl": "nhl",
              "wnba": "wnba", "mlb": "mlb"}


def _pick(row: dict, field: str):
    low = {k.lower().strip(): v for k, v in row.items()}
    for a in ALIASES[field]:
        if a in low and low[a] not in (None, ""):
            return low[a]
    return None


def _price(row: dict) -> float | None:
    p = _pick(row, "prob")
    if p is not None:
        p = float(p)
        return p / 100 if p > 1 else p
    o = _pick(row, "odds")
    if o is None:
        return None
    o = float(str(o).replace("+", ""))
    if 1 < o < 30 and "." in str(o):                      # decimal odds
        return 1 / o
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def _kind(v) -> str:
    v = str(v or "").lower()
    if any(s in v for s in ("total", "over", "under", "o/u")):
        return "total"
    if any(s in v for s in ("spread", "ats", "line", "handicap", "puck", "run line")):
        return "spread"
    return "winner"


def _won(v) -> bool | None:
    v = str(v).strip().lower()
    if v in ("w", "win", "won", "true", "1", "yes", "hit"):
        return True
    if v in ("l", "loss", "lost", "false", "0", "no", "miss"):
        return False
    return None                                            # push / void / pending


def _ts(v) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(v) / (1000 if float(v) > 1e11 else 1)
    except ValueError:
        pass
    for f in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(v)[:25], f).timestamp()
        except ValueError:
            continue
    return 0.0


def load_rows(folder: Path) -> list[dict]:
    rows = []
    for f in sorted(Path(folder).rglob("*")):
        if f.suffix == ".csv":
            rows += list(csv.DictReader(f.open()))
        elif f.suffix == ".json":
            try:
                d = json.loads(f.read_text())
            except ValueError:
                continue
            if isinstance(d, dict):
                d = next((v for v in d.values() if isinstance(v, list)), [d])
            rows += [r for r in d if isinstance(r, dict)]
    return rows


def normalise(rows: list[dict]) -> tuple[list[dict], dict]:
    picks, skipped = [], defaultdict(int)
    for r in rows:
        price, won = _price(r), _won(_pick(r, "result"))
        if price is None:
            skipped["no price/odds column"] += 1
            continue
        if won is None:
            skipped["push / pending / unknown result"] += 1
            continue
        edge = _pick(r, "edge")
        edge = float(edge) if edge is not None else 0.0
        edge = edge / 100 if abs(edge) > 1 else edge       # "4.5" (percent) -> 0.045
        lg = str(_pick(r, "league") or "unknown").lower().strip()
        o, c, clv = _pick(r, "open"), _pick(r, "close"), _pick(r, "clv")
        move = None
        if clv is not None:
            move = float(clv)
        elif o is not None and c is not None:
            try:
                move = float(c) - float(o)
            except ValueError:
                pass
        rank = _pick(r, "rank")
        picks.append({"league": LEAGUE_MAP.get(lg, lg), "kind": _kind(_pick(r, "kind")), "price": round(price, 4),
                      "edge": round(edge, 4), "won": won, "ts": _ts(_pick(r, "ts")), "move": move,
                      "rank": int(float(rank)) if rank not in (None, "") else None, "source": "bigvin"})
    return picks, dict(skipped)


def breakdown(picks: list[dict], dim) -> list[dict]:
    g = defaultdict(list)
    for p in picks:
        g[dim(p)].append(p)
    out = []
    for k, ps in g.items():
        if k is None:
            continue
        pnl = sum((1 - p["price"]) / p["price"] if p["won"] else -1 for p in ps)
        out.append({"group": k, "n": len(ps), "win": sum(p["won"] for p in ps) / len(ps), "roi": pnl / len(ps),
                    "avg_price": sum(p["price"] for p in ps) / len(ps)})
    return sorted(out, key=lambda r: r["roi"])


DIMS = {
    "League": lambda p: p["league"],
    "Bet type": lambda p: p["kind"],
    "Edge size": lambda p: SEG.edge_bucket(p["edge"]),
    "Favourite vs underdog": lambda p: SEG.side_of(p["price"]),
    "Price band": lambda p: f"{int(p['price'] * 10) * 10}-{int(p['price'] * 10) * 10 + 10}c",
    "Line moved with/against the pick": lambda p: None if p["move"] is None else
    ("with" if p["move"] > 0 else "against" if p["move"] < 0 else "flat"),
    "Confidence rank": lambda p: None if p["rank"] is None else ("top 3" if p["rank"] <= 3 else
                                                                 "4-8" if p["rank"] <= 8 else "9+"),
    "League x bet type": lambda p: f"{p['league']} {p['kind']}",
}


def report(picks: list[dict], skipped: dict) -> str:
    L = [f"# Big Vin: what wins, what loses ({len(picks)} graded picks)", "",
         "ROI is per $1 staked at the listed price, before Kalshi fees. Groups are sorted worst first.", ""]
    if skipped:
        L += ["Skipped rows: " + ", ".join(f"{k}: {v}" for k, v in skipped.items()), ""]
    losers = []
    for name, dim in DIMS.items():
        rows = breakdown(picks, dim)
        if not rows:
            continue
        L += [f"## {name}", "", "| group | picks | win % | ROI | avg price |", "|---|---:|---:|---:|---:|"]
        L += [f"| {r['group']} | {r['n']} | {r['win']:.1%} | {r['roi']:+.1%} | {r['avg_price']:.2f} |" for r in rows]
        L.append("")
        losers += [(name, r) for r in rows if r["n"] >= 50 and r["roi"] < -0.03]
    L += ["## Main reasons it loses", ""]
    for name, r in sorted(losers, key=lambda x: x[1]["roi"] * x[1]["n"])[:8]:
        L.append(f"- {name}: **{r['group']}** lost {r['roi']:+.1%} over {r['n']} picks "
                 f"(won {r['win']:.0%} at an average price of {r['avg_price']:.2f}).")
    s = SEG.winrate_search(picks)
    L += ["", "## Strategies that win 60%+ (chosen on the first 70%, judged on the last 30%)", "",
          s["note"], "", "| segment | train n | train win | train ROI | test n | test win | test win (90% low) | test ROI | credible |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in s["hits"]:
        f = lambda v, pct=True: "-" if v is None else (f"{v:.1%}" if pct else str(v))  # noqa: E731
        L.append(f"| {r['segment']} | {r['train_n']} | {f(r['train_win'])} | {f(r['train_roi'])} | {r['test_n']} | "
                 f"{f(r['test_win'])} | {f(r['test_win_low90'])} | {f(r['test_roi'])} | {'yes' if r['credible'] else 'no'} |")
    if not s["credible"]:
        L += ["", "**No segment both wins 60%+ out of sample and makes money there.** "
              "The app sizes by expected profit instead of chasing win rate."]
    table = SEG.build_table(picks)
    L += ["", "## Segment multipliers fed to the app (shrunk toward 0 ROI)", "",
          "| segment | picks | ROI | shrunk ROI | stake x |", "|---|---:|---:|---:|---:|"]
    L += [f"| {k} | {v['n']} | {v['roi']:+.1%} | {v['shrunk_roi']:+.1%} | {v['mult']} |"
          for k, v in sorted(table.items(), key=lambda kv: kv[1]["shrunk_roi"])]
    return "\n".join(L) + "\n"


def main(folder: str | None = None):
    folder = Path(folder or ROOT / "data" / "bigvin")
    rows = load_rows(folder)
    picks, skipped = normalise(rows)
    if not picks:
        cols = sorted({k for r in rows[:200] for k in r})
        print(f"No usable picks in {folder} ({len(rows)} rows). Columns seen: {cols}")
        return 1
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "bigvin_picks.json").write_text(json.dumps(picks))
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "BIG_VIN_LEARNING.md").write_text(report(picks, skipped))
    print(f"{len(picks)} picks -> data/bigvin_picks.json, reports/BIG_VIN_LEARNING.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
