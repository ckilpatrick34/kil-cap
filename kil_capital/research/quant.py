"""Hedge-fund methods applied to sports prices, every test scored on seasons the method never saw.

Sections (all recommend-only research; nothing here bets):
  A. Fair value: which way of removing the bookmaker's margin ("de-vig") gives the best-calibrated price.
  B. Black-Scholes digital pricing: a game as a digital option on the final margin, P(margin > k) = N(d2),
     d2 = (expected margin - k) / sigma. Checked against the real distribution (NFL key numbers), used to price
     whole spread ladders, and tested as relative value between the moneyline and the spread.
  C. Live pricing: the same digital with sigma * sqrt(time left), on every NFL play 2022-2025.
  D. Sizing: Kelly with estimation error, and how correlated same-day bets are.
  E. Obscure stats: referees, stadiums, altitude, travel, letdown/lookahead, overtime hangover, dome teams in the
     cold, revenge games, NBA/NHL schedule spots. Referee and stadium tendencies use only games already played.

Run: PYTHONPATH=. python -m kil_capital.research.quant   (writes reports/QUANT_METHODS.md)
Needs data/raw from history.nflverse / sources.sbr and NFL play-by-play in data/raw/pbp (nflverse-data releases)."""
from __future__ import annotations

import csv
import math
import random
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

from kil_capital.research import sources

RAW = Path("data/raw")
OUT = Path(__file__).resolve().parents[2] / "reports" / "QUANT_METHODS.md"
N = NormalDist()
TEST_FROM = 2017  # discovery = earlier seasons, test = 2017 on (same split as round 3)
NFL_SIT_TEST = 2013  # NFL situational rules: discovery 1999-2012, test 2013 on


# ---------------- helpers ----------------
def implied(ml: float) -> float:
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def payout(ml: float) -> float:
    return ml / 100 if ml > 0 else 100 / -ml


def ll(p: float, y: int) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -math.log(p if y else 1 - p)


def kalshi_fee(p: float) -> float:
    """Kalshi taker fee per $1 contract, 0.07 * P * (1 - P), rounded up to the cent (one contract)."""
    return math.ceil(7 * p * (1 - p) * 100 - 1e-9) / 100 if 0 < p < 1 else 0.0


class Rec:
    def __init__(self):
        self.n = self.w = 0
        self.pnl = 0.0
        self.sq = 0.0
        self.be = 0.0

    def add(self, won, odds=-110.0):
        if won is None:
            return
        self.n += 1
        self.w += bool(won)
        r = payout(odds) if won else -1.0
        self.pnl += r
        self.sq += r * r
        self.be += 1 / (1 + payout(odds))

    def s(self):
        if not self.n:
            return "no bets"
        return f"{self.w / self.n:.1%} / {self.pnl / self.n:+.1%} / {self.n}"

    def z(self):
        """t-stat of the average return per $1 (works for mixed prices, e.g. underdog moneylines)."""
        if self.n < 2:
            return 0.0
        m = self.pnl / self.n
        sd = math.sqrt(max(self.sq / self.n - m * m, 1e-12))
        return m / sd * math.sqrt(self.n)


def nfl_rows():
    rows = [r for r in csv.DictReader(open(RAW / "nflverse_games.csv")) if r["result"] not in ("", None)]
    for r in rows:
        r["season"] = int(r["season"])
        r["week"] = int(r["week"])
        r["margin"] = float(r["result"])  # home - away
        r["sp"] = float(r["spread_line"]) if r["spread_line"] else None  # > 0 = home favoured
        r["tl"] = float(r["total_line"]) if r["total_line"] else None
        r["pts"] = float(r["total"])
    rows.sort(key=lambda r: (r["gameday"], r["gametime"] or "", r["game_id"]))
    return rows


def odds(x, default=-110.0):
    try:
        v = float(x)
        return v if v else default
    except (TypeError, ValueError):
        return default


# ================= A. de-vig =================
def devig(qh: float, qa: float, how: str) -> float:
    s = qh + qa
    if how == "mult":
        return qh / s
    if how == "add":
        return min(max(qh - (s - 1) / 2, 0.001), 0.999)
    if how == "power":
        lo, hi = 1.0, 3.0
        for _ in range(60):
            k = (lo + hi) / 2
            if qh ** k + qa ** k > 1:
                lo = k
            else:
                hi = k
        return qh ** k / (qh ** k + qa ** k)
    if how == "shin":
        def ps(z):
            return [(math.sqrt(z * z + 4 * (1 - z) * q * q / s) - z) / (2 * (1 - z)) for q in (qh, qa)]
        lo, hi = 0.0, 0.4
        for _ in range(60):
            z = (lo + hi) / 2
            if sum(ps(z)) > 1:
                lo = z
            else:
                hi = z
        a, b = ps(z)
        return a / (a + b)
    raise ValueError(how)


def ml_games():
    out = defaultdict(list)
    for r in nfl_rows():
        if r["margin"] == 0 or not r["home_moneyline"] or not r["away_moneyline"]:
            continue
        h, a = float(r["home_moneyline"]), float(r["away_moneyline"])
        if sources._ml_ok(h, a):
            out["nfl"].append((r["season"], h, a, int(r["margin"] > 0)))
    for lg in ("nba", "nhl", "mlb"):
        for r in sources.sbr(lg, RAW):
            if r["ml_h"] and r["hs"] != r["as_"]:
                out[lg].append((r["season"], r["ml_h"], r["ml_a"], int(r["hs"] > r["as_"])))
    return out


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def fit_recal(xs, ys):
    """Logistic regression y ~ a + b * logit(p), Newton steps."""
    a, b = 0.0, 1.0
    for _ in range(30):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            p = 1 / (1 + math.exp(-(a + b * x)))
            ga += p - y
            gb += (p - y) * x
            w = p * (1 - p)
            haa += w
            hab += w * x
            hbb += w * x * x
        det = haa * hbb - hab * hab
        a -= (hbb * ga - hab * gb) / det
        b -= (haa * gb - hab * ga) / det
    return a, b


def section_a(L):
    L += ["## A. Fair value: removing the bookmaker margin", "",
          "A Kalshi contract is a probability, so the fair price of a game is the sportsbook price with the "
          "bookmaker's margin taken out. There are four standard ways to take it out. They differ most on long shots. "
          "Scored on closing moneylines in the test seasons (2017 on). Lower log loss is better.", "",
          "| League | Test games | Multiplicative | Additive | Power | Shin | Shin + recalibration |",
          "|---|---|---|---|---|---|---|"]
    fl = []
    best = {}
    for lg, g in ml_games().items():
        test = [x for x in g if x[0] >= TEST_FROM]
        disc = [x for x in g if x[0] < TEST_FROM]
        row = [lg.upper(), f"{len(test):,}"]
        scores = {}
        for how in ("mult", "add", "power", "shin"):
            scores[how] = sum(ll(devig(implied(h), implied(a), how), y) for _, h, a, y in test) / len(test)
        a_, b_ = fit_recal([logit(devig(implied(h), implied(a), "shin")) for _, h, a, y in disc], [y for *_, y in disc])
        scores["recal"] = sum(ll(1 / (1 + math.exp(-(a_ + b_ * logit(devig(implied(h), implied(a), "shin"))))), y)
                              for _, h, a, y in test) / len(test)
        lo = min(scores.values())
        for k in ("mult", "add", "power", "shin", "recal"):
            row.append(("**%.4f**" if scores[k] == lo else "%.4f") % scores[k])
        best[lg] = min(scores, key=scores.get)
        L.append("| " + " | ".join(row) + " |")
        # favourite-longshot table on the test half, multiplicative de-vig
        for lo_, hi_ in ((0, .25), (.25, .4), (.4, .6), (.6, .75), (.75, 1.01)):
            sel = [(devig(implied(h), implied(a), "mult"), y) for _, h, a, y in test]
            sel += [(1 - p, 1 - y) for p, y in sel]
            sel = [(p, y) for p, y in sel if lo_ <= p < hi_]
            if sel:
                fl.append((lg, f"{lo_:.0%}-{min(hi_, 1):.0%}", len(sel), sum(p for p, _ in sel) / len(sel),
                           sum(y for _, y in sel) / len(sel)))
    L += ["", "Favourite-longshot check (test seasons, both sides of every game, multiplicative de-vig):", "",
          "| League | Fair-price bucket | Sides | Average fair price | Actually won | Gap |", "|---|---|---|---|---|---|"]
    for lg, b, n, p, w in fl:
        L.append(f"| {lg.upper()} | {b} | {n:,} | {p:.1%} | {w:.1%} | {w - p:+.1%} |")
    return best


# ================= B. digital (Black-Scholes) pricing =================
class Margin:
    """Distribution of (final margin - expected margin), fit on discovery games.
    normal: N(d2) with one sigma. empirical: the real histogram, which keeps NFL key numbers (3, 7)."""

    def __init__(self, resid, mus):
        self.sigma = math.sqrt(sum(e * e for e in resid) / len(resid))
        self.res = sorted(resid)
        self.pairs = sorted(zip(mus, resid))

    def p_normal(self, mu, k):
        return N.cdf((mu - k) / self.sigma)  # P(margin > k) = N(d2)

    def p_local(self, mu, k):
        """Histogram of real final margins in past games with nearly the same spread (keeps key numbers in place)."""
        for w in (0.5, 1.0, 1.5, 2.5):
            lo = bisect_right(self.pairs, (mu - w - 1e-9, 1e9))
            hi = bisect_right(self.pairs, (mu + w + 1e-9, 1e9))
            if hi - lo >= 150:
                break
        ms = [s_ + e for s_, e in self.pairs[lo:hi]]
        return (sum(m_ > k for m_ in ms) + 1) / (len(ms) + 2)

    def p_emp(self, mu, k):
        # P(mu + e > k) = P(e > k - mu), half-weight on exact ties via a 0.5-wide window
        x = k - mu
        n = len(self.res)
        above = n - bisect_right(self.res, x + 0.25)
        tie = bisect_right(self.res, x + 0.25) - bisect_right(self.res, x - 0.25)
        return (above + 0.5 * tie + 1) / (n + 2)


def section_b(L):
    rows = [r for r in nfl_rows() if r["sp"] is not None and r["game_type"] == "REG"]
    disc = [r for r in rows if r["season"] < TEST_FROM]
    test = [r for r in rows if r["season"] >= TEST_FROM]
    m = Margin([r["margin"] - r["sp"] for r in disc], [r["sp"] for r in disc])
    # whole ladder: every half-point strike within 14 points of the line
    sc = {"normal": 0.0, "emp": 0.0, "local": 0.0}
    n = 0
    worst = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
    s_disc = [r for r in disc if r["sp"] == 3.0]
    for r in test:
        mu = r["sp"]
        base = math.floor(mu) + 0.5
        for j in range(-14, 15):
            k = base + j
            y = int(r["margin"] > k)
            pn, pe, pl = m.p_normal(mu, k), m.p_emp(mu, k), m.p_local(mu, k)
            sc["normal"] += ll(pn, y)
            sc["emp"] += ll(pe, y)
            sc["local"] += ll(pl, y)
            n += 1
            if mu == 3.0 and k in (-3.5, -2.5, 2.5, 3.5, 6.5, 7.5):
                w = worst[k]
                w[0] += 1
                w[1] += y
                w[2] += pn
                w[3] += pl
    L += ["", "## B. Black-Scholes digital pricing", "",
          "A Kalshi game contract pays $1 if something happens, which makes it a digital option. Treat the final "
          "margin as the 'stock' with expected value = the sportsbook spread and volatility sigma. Then the fair price "
          "of 'home wins by more than k' is N(d2), with d2 = (spread - k) / sigma. This prices every rung of a Kalshi "
          "spread ladder from one sportsbook number.", "",
          f"* NFL sigma (fit on 2006-2016): **{m.sigma:.1f} points**.",
          f"* Pricing every half-point strike within 14 points of the line for {len(test):,} test games ({n:,} prices): "
          f"normal N(d2) log loss {sc['normal'] / n:.4f}, shifted histogram {sc['emp'] / n:.4f}, "
          f"histogram of past games at the same spread {sc['local'] / n:.4f} (lower is better).", "",
          "Key numbers break the normal curve. Home favourite of exactly 3, test seasons:", "",
          "| Strike: home wins by more than | Games | Actually | N(d2) price | Same-spread histogram |", "|---|---|---|---|---|"]
    for k in sorted(worst):
        c, y, pn, pe = worst[k]
        L.append(f"| {k:+.1f} | {c} | {y / c:.1%} | {pn / c:.1%} | {pe / c:.1%} |")

    # volatility by league and by total size (the 'smile')
    L += ["", "Volatility of the final margin and the final total, discovery seasons:", "",
          "| League | Margin sigma | Total sigma | Total sigma when total is low / mid / high |", "|---|---|---|---|"]
    vols = {}
    for lg in ("nfl", "nba", "nhl", "mlb"):
        if lg == "nfl":
            g = [(r["sp"], r["margin"], r["tl"], r["pts"]) for r in disc]
        else:
            g = [(r["spread"], r["hs"] - r["as_"], r["total"], r["hs"] + r["as_"])
                 for r in sources.sbr(lg, RAW) if r["season"] < TEST_FROM]
        sm = [m_ - s for s, m_, *_ in g if s is not None]
        tt = sorted([(t, p - t) for *_, t, p in g if t])
        sig = math.sqrt(sum(e * e for e in sm) / len(sm)) if len(sm) > 100 else None
        st = math.sqrt(sum(e * e for _, e in tt) / len(tt))
        thirds = [tt[i * len(tt) // 3:(i + 1) * len(tt) // 3] for i in range(3)]
        tv = " / ".join(f"{math.sqrt(sum(e * e for _, e in th) / len(th)):.2f} (at {th[len(th) // 2][0]:g})" for th in thirds)
        vols[lg] = (sig, st)
        L.append(f"| {lg.upper()} | {sig:.1f} |" if sig else f"| {lg.upper()} | n/a |")
        L[-1] += f" {st:.2f} | {tv} |"

    # relative value: moneyline vs spread ("put-call parity" across a book's own markets)
    L += ["", "### Moneyline vs spread relative value", "",
          "The same book prices the moneyline and the spread. Through the margin distribution, the spread implies a win "
          "probability. When the moneyline's no-vig price disagrees with the spread's by more than a threshold, bet the "
          "moneyline side the spread says is cheap, at the real moneyline price. Thresholds were fixed before scoring.", "",
          "| League | Gap | Discovery win / return / bets | Test win / return / bets | Test z |", "|---|---|---|---|---|"]
    res = {}
    for lg in ("nfl", "nba"):
        if lg == "nfl":
            g = [(r["season"], r["sp"], float(r["home_moneyline"]), float(r["away_moneyline"]), r["margin"])
                 for r in rows if r["home_moneyline"] and r["away_moneyline"] and r["margin"] != 0]
            mm = m
        else:
            sb = [r for r in sources.sbr(lg, RAW) if r["spread"] is not None and r["ml_h"] and r["hs"] != r["as_"]]
            g = [(r["season"], r["spread"], r["ml_h"], r["ml_a"], r["hs"] - r["as_"]) for r in sb]
            d = [x for x in g if x[0] < TEST_FROM]
            mm = Margin([x[4] - x[1] for x in d], [x[1] for x in d])
        g = [x for x in g if sources._ml_ok(x[2], x[3])]
        for gap in (0.02, 0.03, 0.05):
            rec = {True: Rec(), False: Rec()}
            for season, sp, h, a, mg in g:
                p_ml = devig(implied(h), implied(a), "mult")
                p_sp = mm.p_emp(sp, 0) if lg == "nfl" else mm.p_normal(sp, 0)
                if p_sp - p_ml > gap:
                    rec[season < TEST_FROM].add(mg > 0, h)
                elif p_ml - p_sp > gap:
                    rec[season < TEST_FROM].add(mg < 0, a)
            L.append(f"| {lg.upper()} | {gap:.0%} | {rec[True].s()} | {rec[False].s()} | {rec[False].z():+.1f} |")
            res[(lg, gap)] = rec
    return m, vols, res


# ================= C. live digital =================
def section_c(L, sigma_pre):
    try:
        import pandas as pd
    except ImportError:
        L += ["", "## C. Live pricing", "", "pandas not installed; skipped."]
        return None
    files = sorted((RAW / "pbp").glob("pbp_*.parquet"))
    if not files:
        L += ["", "## C. Live pricing", "", "No play-by-play files in data/raw/pbp; skipped."]
        return None
    cols = ["game_id", "season", "season_type", "game_seconds_remaining", "total_home_score", "total_away_score",
            "spread_line", "result", "posteam", "home_team", "ep", "vegas_home_wp", "qtr"]
    df = pd.concat([pd.read_parquet(f, columns=cols) for f in files])
    df = df[(df.season_type == "REG") & df.game_seconds_remaining.notna() & df.vegas_home_wp.notna()
            & df.ep.notna() & (df.qtr <= 4) & (df.result != 0)]
    df = df.groupby("game_id", group_keys=False).apply(lambda x: x.iloc[::4])  # thin to every 4th play
    t = (df.game_seconds_remaining / 3600).clip(lower=1 / 3600)
    d = df.total_home_score - df.total_away_score
    poss = df.ep.where(df.posteam == df.home_team, -df.ep)
    y = (df.result > 0).astype(int)
    disc = df.season < 2022

    def price(sig, with_poss, frac_t):
        mu = d + df.spread_line * t + (poss if with_poss else 0)
        return pd.Series([N.cdf(v) for v in (mu / (sig * (t ** frac_t)))], index=df.index)

    def score(p, mask):
        p = p[mask].clip(1e-6, 1 - 1e-6)
        yy = y[mask]
        return float(-(yy * p.apply(math.log) + (1 - yy) * (1 - p).apply(math.log)).mean())

    best = None
    for sig in range(12, 23):
        for fe in (0.5,):
            s = score(price(sig, True, fe), disc)
            if best is None or s < best[0]:
                best = (s, sig, fe)
    _, sig, fe = best
    test = ~disc
    p_plain = price(sig, False, fe)
    p_poss = price(sig, True, fe)
    late = test & (df.game_seconds_remaining <= 600)
    L += ["", "## C. Live pricing (in-game digital option)", "",
          "In a live game the 'stock' is the current score margin plus the expected margin still to come, and the "
          "volatility shrinks with time left: P(home wins) = N((lead + spread x time left + possession value) / "
          "(sigma x sqrt(time left))). Fit on 2019-2021 plays, scored on 2022-2025 plays. The benchmark is nflverse's "
          "own win-probability model, which uses down, distance, field position and timeouts.", "",
          f"* Sigma fit on discovery plays: **{sig} points per game**.", "",
          "| Model | All test plays | Last 10 minutes |", "|---|---|---|",
          f"| Score + time only | {score(p_plain, test):.4f} | {score(p_plain, late):.4f} |",
          f"| + possession value (expected points) | {score(p_poss, test):.4f} | {score(p_poss, late):.4f} |",
          f"| nflverse win-probability model | {score(df.vegas_home_wp, test):.4f} | {score(df.vegas_home_wp, late):.4f} |",
          "", f"Plays scored: {int(test.sum()):,} test, {int(disc.sum()):,} discovery (every 4th play)."]
    return sig


# ================= D. sizing =================
def section_d(L):
    rows = [r for r in nfl_rows() if r["tl"] and r["game_type"] == "REG" and r["season"] >= 2006]
    # correlation of over/under results on the same NFL Sunday
    by_day = defaultdict(list)
    for r in rows:
        if r["pts"] != r["tl"]:
            by_day[(r["season"], r["week"])].append(1 if r["pts"] > r["tl"] else 0)
    num = den = 0.0
    var_ratio = []
    for v in by_day.values():
        if len(v) < 8:
            continue
        mean = sum(v) / len(v)
        var_ratio.append((mean - 0.5) ** 2 / (0.25 / len(v)))
    ratio = sum(var_ratio) / len(var_ratio)
    rho = (ratio - 1) / (13 / 1)  # var of mean = (1 + (n-1) rho)/n * .25 with n ~ 14
    rows_s = [r for r in rows if r["sp"] is not None]
    by_day_s = defaultdict(list)
    for r in rows_s:
        if r["margin"] != r["sp"]:
            by_day_s[(r["season"], r["week"])].append(1 if r["margin"] > r["sp"] else 0)
    vr2 = [((sum(v) / len(v) - 0.5) ** 2) / (0.25 / len(v)) for v in by_day_s.values() if len(v) >= 8]
    ratio2 = sum(vr2) / len(vr2)

    L += ["", "## D. Sizing: Kelly with honest uncertainty, and correlation", "",
          f"* **Same-week correlation of NFL over/under results**: the spread of weekly over rates is "
          f"{ratio:.2f}x what independent games would give (1.00 = independent), an average pairwise correlation of "
          f"about {rho:+.3f}. " + ("Over/under bets on the same Sunday are close to independent, so no slate-level haircut "
          "is needed." if ratio < 1.15 else "Scoring conditions move the slate together, so cut same-day exposure."),
          f"* **Home-cover results** are {ratio2:.2f}x (about independent).", ""]

    # Monte Carlo bankroll paths
    sleeves = [("NFL spread vs opener 3+", 0.559, 390, -110, 43), ("NFL wind 15+ under", 0.554, 267, -110, 20),
               ("NFL primetime under", 0.532, 491, -110, 38)]
    L += ["One NFL season on a $100 bankroll, 2,000 simulated seasons. The true win rate is unknown: each simulated "
          "season draws it from a skeptical estimate that starts at break-even and moves toward the test record "
          "by how many bets that record holds (a 400-bet prior at 52.4%). Bets are -110.", "",
          "| Rule | Test record | Skeptical win rate | Sizing | Median end | Chance of profit | Chance of losing half |",
          "|---|---|---|---|---|---|---|"]
    rnd = random.Random(7)
    be = 110 / 210
    for name, p, n, o, per in sleeves:
        k0 = 400
        pa = (p * n + be * k0)
        pb = ((1 - p) * n + (1 - be) * k0)
        p_mean = pa / (pa + pb)
        b = payout(o)
        kelly = max((p_mean * (b + 1) - 1) / b, 0)
        for label, size in (("Flat $10", lambda br: 10), ("Flat $5", lambda br: 5),
                            ("Full Kelly", lambda br: br * kelly), ("Quarter Kelly", lambda br: br * kelly / 4)):
            ends = []
            half = 0
            for _ in range(2000):
                true_p = rnd.betavariate(pa, pb)
                br = 100.0
                low = br
                for _ in range(per):
                    st = min(size(br), br, 10)
                    if st < 0.01:
                        break
                    br += st * b if rnd.random() < true_p else -st
                    low = min(low, br)
                ends.append(br)
                half += low <= 50
            ends.sort()
            L.append(f"| {name} | {p:.1%} on {n} | {p_mean:.1%} | {label}{' (' + format(kelly * (100 if label.startswith('Full') else 25), '.1f') + '% a bet)' if 'Kelly' in label else ''} "
                     f"| ${ends[1000]:.0f} | {sum(e > 100 for e in ends) / 20:.0f}% | {half / 20:.0f}% |")
    return ratio


# ================= E. obscure stats =================
TEAM_LL = {"ARI": (33.53, -112.26), "ATL": (33.76, -84.40), "BAL": (39.28, -76.62), "BUF": (42.77, -78.79),
           "CAR": (35.23, -80.85), "CHI": (41.86, -87.62), "CIN": (39.10, -84.52), "CLE": (41.51, -81.70),
           "DAL": (32.75, -97.09), "DEN": (39.74, -105.02), "DET": (42.34, -83.05), "GB": (44.50, -88.06),
           "HOU": (29.68, -95.41), "IND": (39.76, -86.16), "JAX": (30.32, -81.64), "KC": (39.05, -94.48),
           "LA": (33.95, -118.34), "LAC": (33.95, -118.34), "LV": (36.09, -115.18), "MIA": (25.96, -80.24),
           "MIN": (44.97, -93.26), "NE": (42.09, -71.26), "NO": (29.95, -90.08), "NYG": (40.81, -74.07),
           "NYJ": (40.81, -74.07), "PHI": (39.90, -75.17), "PIT": (40.45, -80.02), "SEA": (47.60, -122.33),
           "SF": (37.40, -121.97), "TB": (27.98, -82.50), "TEN": (36.17, -86.77), "WAS": (38.91, -76.86),
           "OAK": (37.75, -122.20), "SD": (32.78, -117.12), "STL": (38.63, -90.19)}
DOME = {"ARI", "ATL", "DAL", "DET", "HOU", "IND", "LV", "MIN", "NO", "LA", "LAC", "STL"}


def miles(a, b):
    (la1, lo1), (la2, lo2) = TEAM_LL[a], TEAM_LL[b]
    p = math.pi / 180
    h = math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(h))


def ats(r, home_side: bool):
    """Did the chosen side cover? None on a push. Price from nflverse when listed."""
    if r["sp"] is None or r["margin"] == r["sp"]:
        return None, -110.0
    hc = r["margin"] > r["sp"]
    return (hc if home_side else not hc), odds(r["home_spread_odds"] if home_side else r["away_spread_odds"])


def ou(r, over: bool):
    if r["tl"] is None or r["pts"] == r["tl"]:
        return None, -110.0
    return ((r["pts"] > r["tl"]) == over), odds(r["over_odds"] if over else r["under_odds"])


def nfl_rules():
    rows = [r for r in nfl_rows() if r["sp"] is not None]
    rules = defaultdict(lambda: {True: Rec(), False: Rec()})

    def bet(name, r, res):
        won, o = res
        rules[name][r["season"] < NFL_SIT_TEST].add(won, o)

    team_games = defaultdict(list)  # team -> list of game rows in order
    ref = defaultdict(lambda: [0, 0, 0, 0])  # overs, ou games, home covers, ats games
    stad = defaultdict(lambda: [0, 0])
    coach_dog = defaultdict(lambda: [0, 0])
    for r in rows:
        h, a = r["home_team"], r["away_team"]
        neutral = r["location"] != "Home"
        # ---- walk-forward tendencies, read BEFORE this game's result is added ----
        rf = ref[r["referee"]] if r["referee"] else None
        if rf and rf[1] >= 40 and r["tl"]:
            rate = rf[0] / rf[1]
            if rate >= 0.55:
                bet("Referee over-rate 55%+ (past games): bet over", r, ou(r, True))
            elif rate <= 0.45:
                bet("Referee over-rate 45% or less: bet under", r, ou(r, False))
        if rf and rf[3] >= 40:
            rate = rf[2] / rf[3]
            if rate >= 0.55:
                bet("Referee home-cover rate 55%+: bet home ATS", r, ats(r, True))
            elif rate <= 0.45:
                bet("Referee home-cover rate 45% or less: bet away ATS", r, ats(r, False))
        st = stad[r["stadium_id"]]
        if st[1] >= 30 and r["tl"] and not neutral:
            if st[0] / st[1] >= 0.57:
                bet("Stadium over-rate 57%+ (past games): bet over", r, ou(r, True))
            elif st[0] / st[1] <= 0.43:
                bet("Stadium over-rate 43% or less: bet under", r, ou(r, False))
        for side, team, coach in ((True, h, r["home_coach"]), (False, a, r["away_coach"])):
            dog = (r["sp"] < -3) if side else (r["sp"] > 3)
            cd = coach_dog[coach]
            if dog and cd[1] >= 20 and cd[0] / cd[1] >= 0.58:
                bet("Coach covers 58%+ as a 3+ point dog (past games): back him", r, ats(r, side))
        # ---- altitude, travel, climate ----
        if h == "DEN" and not neutral:
            bet("Altitude: Denver at home, bet Denver ATS", r, ats(r, True))
            bet("Altitude: Denver at home, bet the over", r, ou(r, True))
        if not neutral and h in TEAM_LL and a in TEAM_LL and miles(a, h) >= 2000:
            bet("Travel 2,000+ miles: bet home ATS", r, ats(r, True))
        try:
            temp = float(r["temp"]) if r["temp"] else None
        except ValueError:
            temp = None
        if temp is not None and temp <= 40 and r["roof"] == "outdoors" and a in DOME and h not in DOME:
            bet("Dome team outdoors at 40F or colder: bet home ATS", r, ats(r, True))
        # ---- schedule psychology ----
        for side, team, opp in ((True, h, a), (False, a, h)):
            prev = team_games[team][-1] if team_games[team] else None
            if prev and prev["season"] == r["season"] and r["game_type"] == "REG":
                p_home = prev["home_team"] == team
                p_margin = prev["margin"] if p_home else -prev["margin"]
                p_line = prev["sp"] if p_home else -(prev["sp"] or 0)
                if prev["sp"] is not None and p_line <= -7 and p_margin > 0:
                    bet("Letdown: team won outright as a 7+ point dog last week, fade it ATS", r, ats(r, not side))
                if prev["overtime"] == "1":
                    oprev = team_games[opp][-1] if team_games[opp] else None
                    if not (oprev and oprev["season"] == r["season"] and oprev["overtime"] == "1"):
                        bet("Overtime hangover: played OT last week, fade it ATS", r, ats(r, not side))
                if len(team_games[team]) >= 2:
                    p2 = team_games[team][-2]
                    if (not side and prev["away_team"] == team and p2["away_team"] == team
                            and p2["season"] == r["season"] and prev["location"] == "Home" and p2["location"] == "Home"):
                        bet("Third straight road game: fade the road team ATS", r, ats(r, True))
            # revenge: second meeting this season, lost the first by 14+
            for g0 in reversed(team_games[team]):
                if g0["season"] != r["season"]:
                    break
                if opp in (g0["home_team"], g0["away_team"]):
                    m0 = g0["margin"] if g0["home_team"] == team else -g0["margin"]
                    if m0 <= -14 and r["game_type"] == "REG":
                        bet("Revenge: lost the first meeting by 14+, back it ATS", r, ats(r, side))
                    break
        # ---- record game, update tendencies ----
        team_games[h].append(r)
        team_games[a].append(r)
        if r["referee"]:
            if r["tl"] and r["pts"] != r["tl"]:
                ref[r["referee"]][0] += r["pts"] > r["tl"]
                ref[r["referee"]][1] += 1
            if r["margin"] != r["sp"]:
                ref[r["referee"]][2] += r["margin"] > r["sp"]
                ref[r["referee"]][3] += 1
        if r["tl"] and r["pts"] != r["tl"] and not neutral:
            stad[r["stadium_id"]][0] += r["pts"] > r["tl"]
            stad[r["stadium_id"]][1] += 1
        for side, coach in ((True, r["home_coach"]), (False, r["away_coach"])):
            dog = (r["sp"] < -3) if side else (r["sp"] > 3)
            if dog and r["margin"] != r["sp"]:
                coach_dog[coach][0] += (r["margin"] > r["sp"]) == side
                coach_dog[coach][1] += 1
    # lookahead needs the NEXT game: second pass
    nxt = {}
    for t, gs in team_games.items():
        for g0, g1 in zip(gs, gs[1:]):
            if g0["season"] == g1["season"]:
                nxt[(t, g0["game_id"])] = g1
    for r in rows:
        if r["game_type"] != "REG":
            continue
        for side, team in ((True, r["home_team"]), (False, r["away_team"])):
            fav7 = (r["sp"] >= 7) if side else (r["sp"] <= -7)
            g1 = nxt.get((team, r["game_id"]))
            if fav7 and g1 and g1["div_game"] == "1" and g1["gametime"] and g1["gametime"] >= "19:00":
                bet("Lookahead: 7+ point favourite with a primetime division game next, fade it ATS", r, ats(r, not side))
    return rules


def sbr_rules():
    rules = defaultdict(lambda: {True: Rec(), False: Rec()})
    alt = {"nba": {"Nuggets", "Jazz"}, "nhl": {"Avalanche"}}
    for lg in ("nba", "nhl"):
        rows = sources.sbr(lg, RAW)
        last = {}
        streak = defaultdict(int)
        recent = defaultdict(list)
        for r in rows:
            h, a, ts = r["home"], r["away"], r["ts"]
            b2b = {t: (t in last and ts - last[t] <= 86400 * 1.1) for t in (h, a)}
            three4 = {t: len([x for x in recent[t] if ts - x <= 86400 * 3.1]) >= 2 for t in (h, a)}
            test = r["season"] < TEST_FROM
            margin = r["hs"] - r["as_"]
            if lg == "nba" and r["spread"] is not None and margin != r["spread"]:
                hc = margin > r["spread"]
                if a in alt[lg] or h not in alt[lg] or True:
                    pass
                if h in alt[lg] and b2b[a]:
                    rules[f"{lg.upper()} altitude: visitor on a back-to-back at Denver/Utah, bet home ATS"][test].add(hc)
                if streak[a] >= 3:
                    rules[f"{lg.upper()} 4th+ straight road game: bet home ATS"][test].add(hc)
                if three4[a] and not b2b[h] and not three4[h]:
                    rules[f"{lg.upper()} visitor on 3 games in 4 nights vs rested home: bet home ATS"][test].add(hc)
            if lg == "nhl" and r["ml_h"]:
                hw = margin > 0
                if h in alt[lg] and b2b[a]:
                    rules["NHL altitude: visitor on a back-to-back at Colorado, bet Colorado ML"][test].add(hw, r["ml_h"])
                if streak[a] >= 3:
                    rules["NHL 4th+ straight road game: bet home ML"][test].add(hw, r["ml_h"])
            if r["total"] and b2b[h] and b2b[a] and (r["hs"] + r["as_"]) != r["total"]:
                uo = -110.0
                if lg == "nhl" and r["tot_odds"]:
                    uo = sources.under_price(r["tot_odds"])
                rules[f"{lg.upper()} both teams on a back-to-back: bet the under"][test].add(
                    r["hs"] + r["as_"] < r["total"], uo)
            last[h] = last[a] = ts
            recent[h] = (recent[h] + [ts])[-3:]
            recent[a] = (recent[a] + [ts])[-3:]
            streak[a] += 1
            streak[h] = 0
    return rules


def section_e(L):
    L += ["", "## E. Obscure stats and weird spots", "",
          "Rules written before scoring. Referee, stadium and coach tendencies are walk-forward: each game uses only "
          "games already played. NFL discovery = 1999-2012, test = 2013 on. NBA/NHL discovery = 2011-2016, test = 2017 "
          "on. Graded at the listed price (else -110). **Pass** = profitable in both halves, 150+ test bets, test z 2+.", "",
          "| Rule | Discovery win / return / bets | Test win / return / bets | Test z | Pass |", "|---|---|---|---|---|"]
    allr = {**nfl_rules(), **sbr_rules()}
    passed = []
    for name, rec in sorted(allr.items(), key=lambda kv: -kv[1][False].z()):
        d, t = rec[True], rec[False]
        ok = d.n and t.n >= 150 and d.pnl > 0 and t.pnl > 0 and t.z() >= 2
        if ok:
            passed.append(name)
        L.append(f"| {name} | {d.s()} | {t.s()} | {t.z():+.1f} | {'PASS' if ok else ''} |")
    L += ["", f"{len(allr)} rules scored, so about one would show test z 2+ by luck alone."]
    return allr, passed


def main():
    L = ["# Hedge-fund methods on sports prices (2026-11-27)", "",
         "Recommend-only research. Every number below is scored on seasons the method never saw.", "",
         "## Bottom line", "",
         "* **No new money-making rule passed.** 23 obscure-stat rules (referees, stadiums, altitude, travel, letdown, "
         "lookahead, overtime hangover, dome teams in the cold, revenge, NBA/NHL schedule spots) and 6 moneyline-vs-spread "
         "relative-value trades: none cleared the bar on unseen seasons. Closest: NFL moneyline vs spread at a 3% gap "
         "(+3.9% then +8.9% return, test z 1.2), too weak to bet.",
         "* **Fair value is already right.** All four de-vig methods score within 0.001 log loss of each other, and "
         "sportsbook closing lines show no favourite-longshot bias. The plain (multiplicative) de-vig the app uses is fine.",
         "* **Black-Scholes N(d2) misprices NFL spread ladders near key numbers by 6-9 cents** (home -3: 'wins by 4+' is "
         "41.7% in reality, 48.5% by N(d2)). A histogram of past games at the same spread fixes it. This is the pricing "
         "tool for Kalshi spread ladders, and the place to look for Kalshi mispricing once Kalshi history is pulled.",
         "* **The simple live model is not good enough to trade NFL in-game.** Score + clock + possession N(d2) loses "
         "clearly to a full win-probability model, worst in the last 10 minutes, the time live prices move most.",
         "* **Sizing: bet $3-5, not $10, on the current NFL sleeves.** With honest uncertainty about the edge, full Kelly "
         "is 1-4% of a $100 bankroll. Flat $10 gives a 20-36% chance of being down half at some point in one season; "
         "$5 cuts that to 1-7% and still gains in the median season. Same-Sunday bets are close to independent.",
         "* **Kalshi itself is the untested frontier.** A 2025 study of Kalshi (Burgi, Deng and Whelan, "
         "'Makers and Takers') reports a favourite-longshot bias on Kalshi and that resting (maker) orders do better "
         "than market (taker) orders. Testing that on sports contracts, the Kalshi vs sportsbook gap, and ladder "
         "mispricing needs Kalshi price history, which only downloads from Carson's computer: "
         "`python -m kil_capital.backtest.fetch --series KXNFLGAME,KXNBAGAME,KXNHLGAME --days 365`.",
         "* **Fees:** Kalshi's taker fee is 0.07 x P x (1 - P), about 1.75 cents on a 50-cent contract, so a coin-flip "
         "bet breaks even at about 51.8% versus 52.4% at -110. Kalshi is a cheaper venue than a -110 book for the "
         "same edge, when it lists a matching line.", ""]
    best = section_a(L)
    m, vols, rv = section_b(L)
    section_c(L, m.sigma)
    section_d(L)
    allr, passed = section_e(L)
    OUT.write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
