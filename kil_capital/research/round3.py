"""Strategy search, round 3: return first, judged only on seasons the rule never saw.

Two families, none tested in earlier rounds:
  1. Opener vs model. Build an Elo rating from past results only, compare it with the OPENING line, and bet the
     model's side at the opening price when they disagree by a threshold. The threshold and Elo settings are
     picked on the discovery seasons; the test seasons are scored once, at the end.
  2. NFL situations the earlier rounds skipped: west-coast teams in early kickoffs, Thursday and primetime
     totals, freezing games, teams off a bye.

Every row reports win rate AND return (profit per $1 staked) at the price actually listed: the opening
moneyline, or -110 for spreads and totals when no price is listed. Recommend-only research; nothing bets.
Run: PYTHONPATH=. python -m kil_capital.research.round3   (writes reports/ROUND3_RETURN.md)"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

RAW = Path("data/raw")
OUT = Path(__file__).resolve().parents[2] / "reports" / "ROUND3_RETURN.md"
WORD = {"open": "opening", "close": "closing"}
TEST_FROM = {"nfl": 2017, "nhl": 2017, "mlb": 2017, "nba": 2017}  # discovery = earlier seasons


# ---------------- grading ----------------
def payout(odds: float) -> float:
    """Profit per $1 staked at American odds."""
    odds = float(odds)
    return odds / 100 if odds > 0 else 100 / -odds


def implied(odds: float) -> float:
    odds = float(odds)
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


class Book:
    def __init__(self):
        self.n = self.w = 0
        self.pnl = 0.0

    def add(self, won: bool | None, odds: float = -110):
        if won is None:  # push
            return
        self.n += 1
        self.w += won
        self.pnl += payout(odds) if won else -1

    def row(self):
        if not self.n:
            return "–", "–", 0
        return f"{self.w / self.n:.1%}", f"{self.pnl / self.n:+.1%}", self.n

    def z(self, be=110 / 210):
        return (self.w - self.n * be) / math.sqrt(self.n * be * (1 - be)) if self.n else 0


# ---------------- data ----------------
def sbr(lg: str) -> list[dict]:
    rows = []
    for r in json.load(open(RAW / "sbr" / "data" / f"{lg}_archive_10Y.json")):
        try:
            hs, as_ = float(r["home_final"]), float(r["away_final"])
        except (TypeError, ValueError, KeyError):
            continue
        r["hs"], r["as"], r["d"] = hs, as_, int(r["date"])
        rows.append(r)
    return sorted(rows, key=lambda r: r["d"])


# ---------------- Elo (past results only) ----------------
def elo_probs(rows, k: float, hfa: float, carry: float, mov: bool):
    """Pre-game home win prob for each row; ratings shrink toward 1500 by `carry` between seasons."""
    R: dict[str, float] = defaultdict(lambda: 1500.0)
    season = None
    out = []
    for r in rows:
        if r["season"] != season:
            season = r["season"]
            for t in R:
                R[t] = 1500 + carry * (R[t] - 1500)
        h, a = r["home_team"], r["away_team"]
        diff = R[h] + hfa - R[a]
        p = 1 / (1 + 10 ** (-diff / 400))
        out.append((p, diff))
        res = 1.0 if r["hs"] > r["as"] else 0.0 if r["hs"] < r["as"] else 0.5
        m = math.log(abs(r["hs"] - r["as"]) + 1) if mov else 1.0
        R[h] += k * m * (res - p)
        R[a] -= k * m * (res - p)
    return out


def logloss(ps, rows):
    s = n = 0
    for (p, _), r in zip(ps, rows):
        if r["hs"] == r["as"]:
            continue
        y = r["hs"] > r["as"]
        p = min(max(p, 1e-4), 1 - 1e-4)
        s -= math.log(p if y else 1 - p)
        n += 1
    return s / n


def tune(rows, disc):
    """Pick Elo settings on discovery seasons only."""
    best = None
    for k in (4, 8, 12, 20, 30):
        for hfa in (20, 35, 50, 65):
            for carry in (0.5, 0.75):
                for mov in (False, True):
                    ps = elo_probs(rows, k, hfa, carry, mov)
                    idx = [i for i, r in enumerate(rows) if disc(r) and r["season"] != rows[0]["season"]]
                    ll = logloss([ps[i] for i in idx], [rows[i] for i in idx])
                    if best is None or ll < best[0]:
                        best = (ll, k, hfa, carry, mov)
    return best


# ---------------- family 1: opener vs model, moneyline ----------------
def opener_ml(lg: str):
    # NBA and NFL archives carry only closing moneylines; NHL and MLB have openers too.
    lines = ("open", "close") if lg in ("nhl", "mlb") else ("close",)
    rows = sbr(lg)
    t0 = TEST_FROM[lg]
    disc = lambda r: r["season"] < t0  # noqa: E731
    ll, k, hfa, carry, mov = tune(rows, disc)
    ps = elo_probs(rows, k, hfa, carry, mov)
    res = []
    for th in (0.03, 0.05, 0.08, 0.10):
        for which in lines:
            books = {"disc": Book(), "test": Book()}
            for (p, _), r in zip(ps, rows):
                if r["season"] == rows[0]["season"] or r["hs"] == r["as"]:
                    continue
                try:
                    ho, ao = float(r[f"home_{which}_ml"]), float(r[f"away_{which}_ml"])
                except (KeyError, TypeError, ValueError):
                    continue
                if abs(ho) < 100 or abs(ao) < 100:
                    continue
                ih, ia = implied(ho), implied(ao)
                # Data hygiene: ~40% of MLB archive rows pair prices with no bookmaker margin (sum < 100%),
                # i.e. mismatched sides or books. Those inflate returns, so keep only real two-way markets.
                if not 1.0 <= ih + ia <= 1.08:
                    continue
                mh = ih / (ih + ia)  # vig-free market home chance
                side = "h" if p - mh >= th else "a" if mh - p >= th else None
                if not side:
                    continue
                won = (r["hs"] > r["as"]) == (side == "h")
                books["test" if r["season"] >= t0 else "disc"].add(won, ho if side == "h" else ao)
            res.append((th, which, books))
    return (k, hfa, carry, mov, ll), res


# ---------------- family 1b: opener vs model, NFL spread ----------------
def opener_spread_nfl():
    rows = [r for r in sbr("nfl") if r.get("home_open_spread") not in (None, "")]
    t0 = TEST_FROM["nfl"]
    ll, k, hfa, carry, mov = tune(rows, lambda r: r["season"] < t0)
    ps = elo_probs(rows, k, hfa, carry, mov)
    res = []
    for th in (2.0, 3.0, 4.0, 5.0):
        for which in ("open", "close"):
            books = {"disc": Book(), "test": Book()}
            for (_, diff), r in zip(ps, rows):
                if r["season"] == rows[0]["season"]:
                    continue
                try:
                    line = float(r[f"home_{which}_spread"])
                    opener = float(r["home_open_spread"])
                except (KeyError, TypeError, ValueError):
                    continue
                # Data hygiene: 260 archive rows hold the TOTAL in the closing-spread field (values up to 55).
                # Keep only a closing spread that is a plausible move from the opener.
                if abs(line) > 25 or abs(line - opener) > 7:
                    continue
                model_margin = diff / 25  # 25 Elo points ~ 1 NFL point (538 convention)
                gap = model_margin + line  # >0: model likes home more than the line
                side = "h" if gap >= th else "a" if gap <= -th else None
                if not side:
                    continue
                cover = r["hs"] - r["as"] + line
                won = None if cover == 0 else (cover > 0) == (side == "h")
                books["test" if r["season"] >= t0 else "disc"].add(won)
            res.append((th, which, books))
    return (k, hfa, carry, mov, ll), res


# ---------------- family 2: NFL situations (nflverse, listed odds) ----------------
WEST = {"LA", "LAC", "SD", "SF", "SEA", "OAK", "LV"}


def nfl_situations():
    rows = [r for r in csv.DictReader(open(RAW / "nflverse_games.csv")) if r["result"] and r["spread_line"]]
    t0 = 2013  # discovery 1999-2012, test 2013 on (same split as the NEW_IDEAS round)
    num = lambda v, d=None: float(v) if v not in ("", "NA", None) else d  # noqa: E731
    systems = {
        "West-coast road team in a 1 PM ET kickoff: bet home ATS": lambda r: (
            r["away_team"] in WEST and r["gametime"] and r["gametime"] <= "13:05"
            and r["home_team"] not in WEST, "home_ats"),
        "Thursday night: bet the under": lambda r: (r["weekday"] == "Thursday" and r["game_type"] == "REG", "under"),
        "Primetime (Sun/Mon night): bet the under": lambda r: (
            r["weekday"] in ("Sunday", "Monday") and r["gametime"] >= "19:00", "under"),
        "Freezing (32F or colder, outdoors): bet the under": lambda r: (
            r["roof"] in ("outdoors", "open") and num(r["temp"], 99) <= 32, "under"),
        "Team off a bye vs team that played: bet rested team ATS": lambda r: (
            abs(num(r["home_rest"], 7) - num(r["away_rest"], 7)) >= 6 and r["game_type"] == "REG",
            "home_ats" if num(r["home_rest"], 7) > num(r["away_rest"], 7) else "away_ats"),
        "Divisional game, total 41 or less: bet the over": lambda r: (
            r["div_game"] == "1" and num(r["total_line"], 99) <= 41, "over"),
        "Playoffs: bet the home favourite ATS": lambda r: (
            r["game_type"] != "REG" and num(r["spread_line"], 0) > 0, "home_ats"),
    }
    out = []
    for name, f in systems.items():
        books = {"disc": Book(), "test": Book()}
        for r in rows:
            hit, bet = f(r)
            if not hit:
                continue
            margin, sp = float(r["result"]), float(r["spread_line"])  # result = home - away; spread_line > 0 = home fav
            if bet.endswith("ats"):
                cover = margin - sp
                won = None if cover == 0 else (cover > 0) == (bet == "home_ats")
                odds = num(r["home_spread_odds" if bet == "home_ats" else "away_spread_odds"], -110)
            else:
                tot, line = float(r["total"]), num(r["total_line"])
                if line is None:
                    continue
                won = None if tot == line else (tot > line) == (bet == "over")
                odds = num(r["over_odds" if bet == "over" else "under_odds"], -110)
            books["test" if int(r["season"]) >= t0 else "disc"].add(won, odds)
        out.append((name, books))
    return out


# ---------------- report ----------------
def main():
    L = ["# Strategy search, round 3: return next to win rate",
         "",
         "Every rule is scored on seasons it never saw. Settings and thresholds were chosen on the earlier",
         "(discovery) seasons only; the test seasons were looked at once. Return is profit per $1 staked at the",
         "price actually listed (the opening moneyline, or the listed spread/total odds, else -110).",
         "Recommend-only research: nothing here bets.", "",
         "Data hygiene: about 40% of MLB archive rows pair two prices with no bookmaker margin (mismatched",
         "sides or books) and 260 NFL rows carry the total in the closing-spread field. Both inflated returns",
         "badly on a first pass (a fake 75% NFL spread system), so those rows are dropped before scoring.", ""]
    keep = []
    for lg in ("nhl", "mlb", "nba", "nfl"):
        (k, hfa, carry, mov, ll), res = opener_ml(lg)
        L += [f"## {lg.upper()} moneyline: Elo vs the line (test seasons {TEST_FROM[lg]} on)", "",
              f"Elo tuned on discovery seasons: K {k}, home edge {hfa}, carry-over {carry}, margin {'on' if mov else 'off'}"
              f" (log loss {ll:.4f}).", "",
              "| Bet the model side when it beats the market by | Line | Discovery win / return / bets | Test win / return / bets |",
              "|---|---|---|---|"]
        for th, which, b in res:
            d, t = b["disc"].row(), b["test"].row()
            L.append(f"| {th:.0%} | {which} | {d[0]} / {d[1]} / {d[2]} | {t[0]} / {t[1]} / {t[2]} |")
            keep.append((f"{lg.upper()} ML, model beats {WORD[which]} line by {th:.0%}", b))
        L.append("")
    (k, hfa, carry, mov, ll), res = opener_spread_nfl()
    L += ["## NFL spread: Elo margin vs the line (test seasons 2017 on)", "",
          "| Bet when model and line differ by | Line | Discovery win / return / bets | Test win / return / bets |",
          "|---|---|---|---|"]
    for th, which, b in res:
        d, t = b["disc"].row(), b["test"].row()
        L.append(f"| {th:g} pts | {which} | {d[0]} / {d[1]} / {d[2]} | {t[0]} / {t[1]} / {t[2]} |")
        keep.append((f"NFL spread, model vs {WORD[which]} line by {th:g} pts", b))
    L += ["", "## NFL situations (nflverse 1999-2025, test seasons 2013 on)", "",
          "| Rule | Discovery win / return / bets | Test win / return / bets |", "|---|---|---|"]
    for name, b in nfl_situations():
        d, t = b["disc"].row(), b["test"].row()
        L.append(f"| {name} | {d[0]} / {d[1]} / {d[2]} | {t[0]} / {t[1]} / {t[2]} |")
        keep.append((name, b))
    # Leads: positive return in BOTH halves on 100+ test bets
    leads = sorted(((n, b) for n, b in keep if b["test"].n >= 100 and b["disc"].pnl > 0 and b["test"].pnl > 0),
                   key=lambda x: -x[1]["test"].pnl / x[1]["test"].n)
    L += ["", "## Leads: positive return in discovery AND test, 100+ test bets", ""]
    L += [f"- **{n}**: test {b['test'].row()[0]} win, {b['test'].row()[1]} return on {b['test'].n} bets "
          f"(discovery {b['disc'].row()[0]}, {b['disc'].row()[1]})" for n, b in leads] or ["- None."]
    L += ["", f"{len(keep)} rule/threshold combinations were scored, so a few positive test results are expected by luck alone.",
          "Treat a lead as worth paper-testing, not as proven."]
    OUT.write_text("\n".join(L) + "\n")
    summary = [{"name": n, "test_win": b["test"].w / b["test"].n, "test_return": b["test"].pnl / b["test"].n,
                "test_n": b["test"].n, "disc_win": b["disc"].w / b["disc"].n if b["disc"].n else None,
                "disc_return": b["disc"].pnl / b["disc"].n if b["disc"].n else None} for n, b in leads]
    print("\n".join(L))
    return summary


if __name__ == "__main__":
    main()
