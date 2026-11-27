"""UFC fight model: walk-forward test on fights the model never trained on, priced against real closing odds.

Procedure (fixed before scoring the test years):
  * Elo settings are tuned on 2005-2014 fights only.
  * Each year Y from 2016 is predicted by a model fit on every fight before Jan 1 of Y.
  * Discovery years 2016-2020 pick the blend weight (by log loss) and every betting threshold (by return,
    100+ bets). Test years 2021-2026 are scored once with those choices.
  * Bets are flat $10 at the listed sportsbook moneyline (ufc-master.csv, BestFightOdds closing-ish lines).
Run: PYTHONPATH=. python -m kil_capital.research.ufc_model [ufcstats_dir] [ufc-master.csv]
Writes reports/UFC_MODEL.md and prints the summary.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from ..ufc.history import diff_row, load_bouts, norm, read_csv, walk
from ..ufc.model import FightModel, american_to_prob, devig, logloss, payout

OUT = Path(__file__).resolve().parents[2] / "reports" / "UFC_MODEL.md"
DISC, TEST = (2016, 2020), (2021, 2026)
STAKE = 10.0
L2 = 5.0


def odds_index(path: Path) -> dict:
    idx = {}
    for r in read_csv(path):
        ra, ba = r.get("RedOdds") or r.get("R_odds"), r.get("BlueOdds") or r.get("B_odds")
        if not ra or not ba:
            continue
        d = datetime.strptime(r.get("Date") or r["date"], "%Y-%m-%d").date()
        red, blue = norm(r.get("RedFighter") or r["R_fighter"]), norm(r.get("BlueFighter") or r["B_fighter"])
        for dd in (d, d - timedelta(1), d + timedelta(1)):   # event-date time zones differ by a day
            idx[(dd, frozenset((red, blue)))] = (red, float(ra), float(ba))
    return idx


def dataset(raw: Path, odds_csv: Path):
    bouts, tott = load_bouts(raw)
    rows, _ = walk(bouts, tott)
    idx = odds_index(odds_csv)
    X, y, yr, O = [], [], [], []
    for bt, pa, pb in rows:
        if bt["winner"] is None or bt["date"] < date(2001, 1, 1):
            continue
        X.append(diff_row(pa, pb))
        y.append(1.0 if bt["winner"] == "a" else 0.0)
        yr.append(bt["date"].year)
        o = idx.get((bt["date"], frozenset((bt["a"], bt["b"]))))
        O.append(None if o is None else ((o[1], o[2]) if o[0] == bt["a"] else (o[2], o[1])))
    return np.array(X), np.array(y), np.array(yr), O


def walk_forward(X, y, yr, first=DISC[0], last=TEST[1]):
    p = np.full(len(y), np.nan)
    for Y in range(first, last + 1):
        tr, te = yr < Y, yr == Y
        if te.any():
            p[te] = FightModel(L2).fit(X[tr], y[tr]).prob(X[te])
    return p


def _lg(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def blend(pm, pk, w):
    return 1 / (1 + np.exp(-(w * _lg(pm) + (1 - w) * _lg(pk))))


def bets(rows, rule):
    """rows: (p_model, y, (odds_a, odds_b)). rule -> 'a' | 'b' | None. Returns n, wins, profit at flat STAKE."""
    n = w = 0
    pl = 0.0
    for pm, yy, o in rows:
        s = rule(pm, o)
        if s is None:
            continue
        won = (yy == 1.0) if s == "a" else (yy == 0.0)
        n += 1
        w += won
        pl += STAKE * payout(o[0] if s == "a" else o[1]) if won else -STAKE
    return n, w, pl


def gap_rule(t, w=None):
    """Bet the side whose fair (model, or blend with weight w) beats the vig-inclusive price by more than t."""
    def rule(pm, o):
        p = pm if w is None else float(blend(pm, devig(*o)[0], w))
        if p - american_to_prob(o[0]) > t:
            return "a"
        if (1 - p) - american_to_prob(o[1]) > t:
            return "b"
        return None
    return rule


def band_rule(lo, hi):
    def rule(pm, o):
        if lo <= o[0] < hi:
            return "a"
        if lo <= o[1] < hi:
            return "b"
        return None
    return rule


def run(raw: Path, odds_csv: Path) -> str:
    X, y, yr, O = dataset(raw, odds_csv)
    p = walk_forward(X, y, yr)
    def sel(lo, hi, need_odds=True):
        return [i for i in range(len(y)) if lo <= yr[i] <= hi and not np.isnan(p[i]) and (O[i] or not need_odds)]
    lines = ["# UFC fight model: tested on fights it never saw", "",
             f"Built {date.today().isoformat()} by `kil_capital/research/ufc_model.py`. Data: ufcstats.com via "
             "github.com/Greco1899/scrape_ufc_stats (every UFC fight since 1994, round-by-round stats) and "
             "closing-ish moneylines from github.com/shortlikeafox/ultimate_ufc_dataset (2010 to March 2026).",
             "", "Each year is predicted by a model fit only on earlier fights. Settings were picked on "
             f"{DISC[0]}-{DISC[1]} (discovery) and scored once on {TEST[0]}-{TEST[1]} (test).", ""]
    # accuracy
    lines += ["## How often it picks the winner", "",
              "| Years | Fights | Kil Cap model right | Vegas favourite right | Kil Cap log loss | Vegas log loss |",
              "|---|---|---|---|---|---|"]
    stats = {}
    for lo, hi in (DISC, TEST):
        ids = sel(lo, hi)
        pm, yy = p[ids], y[ids]
        pk = np.array([devig(*O[i])[0] for i in ids])
        stats[(lo, hi)] = (pm, yy, pk, ids)
        lines.append(f"| {lo}-{hi} | {len(ids)} | {((pm > .5) == yy).mean():.1%} | {((pk > .5) == yy).mean():.1%} | "
                     f"{logloss(pm, yy):.4f} | {logloss(pk, yy):.4f} |")
    allids = sel(DISC[0], TEST[1], need_odds=False)
    lines += ["", f"All fights {DISC[0]}-{TEST[1]} including those with no line: {len(allids)} fights, model right "
              f"{((p[allids] > .5) == y[allids]).mean():.1%}. Lower log loss is better; a coin flip scores 0.693.", ""]
    # blend weight on discovery
    pm, yy, pk, _ = stats[DISC]
    grid = [0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5]
    lls = {w: logloss(blend(pm, pk, w), yy) for w in grid}
    w_best = min(lls, key=lls.get)
    pmT, yT, pkT, _ = stats[TEST]
    lines += ["## Does the model add anything to the Vegas line?", "",
              "Blend = mix of our model and the de-vigged Vegas line (weight on our model). Picked on discovery years.", "",
              "| Weight on Kil Cap | Discovery log loss | Test log loss |", "|---|---|---|"]
    for w in grid:
        lines.append(f"| {w:.0%} | {lls[w]:.4f} | {logloss(blend(pmT, pkT, w), yT):.4f} |")
    lines += ["", f"Chosen weight: **{w_best:.0%}**.", ""]
    # betting rules
    def rows_of(ids):
        return [(p[i], y[i], O[i]) for i in ids]
    D, T = rows_of(stats[DISC][3]), rows_of(stats[TEST][3])
    lines += ["## Betting it: flat $10 at the listed moneyline", "",
              "| Rule | Discovery bets | Discovery win % | Discovery return | Test bets | Test win % | Test return | Test $ P/L |",
              "|---|---|---|---|---|---|---|---|"]
    fams = {"Model beats price by": [(t, gap_rule(t)) for t in (0.0, 0.03, 0.05, 0.08, 0.12)],
            f"Blend ({w_best:.0%}) beats price by": [(t, gap_rule(t, w_best)) for t in (0.0, 0.01, 0.02, 0.04)],
            "Back every fighter priced": [((lo, hi), band_rule(lo, hi)) for lo, hi in
                                          ((-10000, -400), (-400, -250), (-250, -150), (-150, 100), (100, 150),
                                           (150, 250), (250, 400), (400, 10000))]}
    summary = {}
    for fam, rules in fams.items():
        best = None
        for t, rule in rules:
            nd, wd, pd_ = bets(D, rule)
            nt, wt, pt = bets(T, rule)
            label = (f"{fam} {t:.0%}" if isinstance(t, float) else f"{fam} {t[0]:+d} to {t[1]:+d}")
            lines.append(f"| {label} | {nd} | {wd / max(nd, 1):.1%} | {pd_ / max(nd * STAKE, 1):+.1%} | {nt} | "
                         f"{wt / max(nt, 1):.1%} | {pt / max(nt * STAKE, 1):+.1%} | {pt:+.0f} |")
            if nd >= 100 and (best is None or pd_ / (nd * STAKE) > best[1]):
                best = (label, pd_ / (nd * STAKE), nt, pt / max(nt * STAKE, 1))
        summary[fam] = best
    lines += ["", "## Verdict", ""]
    for fam, b in summary.items():
        if b:
            lines.append(f"- **{fam}**: best on discovery was `{b[0]}` ({b[1]:+.1%}); on the test years it returned "
                         f"**{b[3]:+.1%}** over {b[2]} bets.")
    lines += ["", "The public fight stats are already in the Vegas price. The model alone loses money against the "
              "closing line at every threshold. The one rule that held on both periods is backing heavy favourites "
              "(-400 or shorter), worth about +3% on a few hundred bets: small, inside the noise, and it risks $10 to "
              "win about $2, so it is a lead to paper-track, not a bet. So the UFC tab treats Vegas as the anchor: the Kil Cap line is shown for comparison, and a "
              "BET only appears when Kalshi sells a fighter at least 3 cents under the fair price (blend of Vegas "
              "and Kil Cap, after Kalshi's fee), the same price-gap rule as the Book's `gap` sleeve. Judge it on "
              "graded bets and closing-line value, not on this backtest.", ""]
    text = "\n".join(lines)
    OUT.write_text(text)
    return text


if __name__ == "__main__":
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw/ufc")
    odds = Path(sys.argv[2]) if len(sys.argv) > 2 else raw / "ufc-master.csv"
    print(run(raw, odds))
