"""Moneyball MLB model from Retrosheet play-by-play (research only, paper).

Per game, season-to-date (before the game) rates, regressed to league mean:
  starting pitcher: K%, BB%, FB%, xFIP per PA, wOBA allowed
  team batting wOBA, bullpen xFIP per PA, run differential per game
Target: home win. Train old seasons, test unseen seasons.

  python -m kil_capital.research.mlb /home/claude/data_mlb/rs/seasons
"""
import csv, glob, math, os, re, sys
from datetime import datetime
from collections import defaultdict

W = dict(BB=0.69, HBP=0.72, S=0.88, D=1.25, T=1.58, HR=2.03)  # snip: fixed wOBA weights; year-specific when it matters
STAT = ("PA", "K", "BB", "IBB", "HBP", "S", "D", "T", "HR", "FB", "BIP")


def classify(ev):
    """Return (counts dict) for one play string, or None if not a plate appearance."""
    base = ev.split(".")[0]
    main, _, mods = base.partition("/")
    m = main.split("+")[0]
    c = {}
    if m.startswith("K"):
        c["K"] = 1
    elif m in ("W", "I", "IW"):
        c["BB"] = 1
        if m != "W":
            c["IBB"] = 1
    elif m == "HP":
        c["HBP"] = 1
    elif m.startswith("HR") or m == "H" or re.match(r"H\d", m):
        c["HR"] = 1; c["FB"] = 1
    elif m.startswith("DGR") or re.match(r"D\d?$|D\d", m):
        c["D"] = 1
    elif re.match(r"T\d?", m):
        c["T"] = 1
    elif re.match(r"S\d?", m) and not m.startswith("SB"):
        c["S"] = 1
    elif re.match(r"\d", m) or m.startswith(("E", "FC")):
        pass  # ball in play, out or reached on error / FC
    else:
        return None  # SB, CS, WP, PB, BK, NP, DI, OA, PO, FLE, C (interference)
    if not any(k in c for k in ("K", "BB", "HBP")):
        c["BIP"] = 1
        if re.search(r"/(F|P|BP)\b|/(F|P)\d", "/" + mods) and "HR" not in c:
            c["FB"] = 1
    if "/SH" in base:
        return None  # sacrifice bunts excluded from rates
    c["PA"] = 1
    return c


def parse_events(path):
    """Yield (game_id, date, number, vis, home, {(team_side, pitcher_id, is_starter): counts}, {side: batting counts}, info)."""
    gid = None
    for line in open(path, encoding="latin-1"):
        f = line.rstrip("\n").split(",")
        t = f[0]
        if t == "id":
            if gid:
                yield gid, info, sp, pit, bat
            gid, info, sp = f[1], {}, {}
            pit = defaultdict(lambda: defaultdict(int)); bat = {0: defaultdict(int), 1: defaultdict(int)}
            cur = {}
        elif t == "info":
            info[f[1]] = f[2] if len(f) > 2 else ""
        elif t in ("start", "sub"):
            side = int(f[-3]); pos = f[-1]
            if pos == "1":
                cur[side] = f[1]
                if t == "start":
                    sp[side] = f[1]
        elif t == "play" and len(f) >= 7:
            c = classify(f[6])
            if not c:
                continue
            bs = int(f[2]); fs = 1 - bs; p = cur.get(fs)
            for k, v in c.items():
                bat[bs][k] += v
                pit[(fs, p, p == sp.get(fs))][k] += v
    if gid:
        yield gid, info, sp, pit, bat


def game_logs(root, years):
    out = {}
    for y in years:
        p = os.path.join(root, str(y), f"GL{y}.TXT")
        for r in csv.reader(open(p, encoding="latin-1")):
            key = (r[6], r[0], r[1])  # home, yyyymmdd, game number
            out[key] = (int(r[9]), int(r[10]))
    return out


def rate(d, k, prior, n0):
    return (d.get(k, 0) + prior * n0) / (d.get("PA", 0) + n0)


def woba(d):
    num = sum(W[k] * d.get(k, 0) for k in W) - W["BB"] * d.get("IBB", 0)
    return num, d.get("PA", 0) - d.get("IBB", 0)


def build(root, years):
    scores = game_logs(root, years)
    rows = []
    for y in years:
        games = []
        for p in glob.glob(os.path.join(root, str(y), f"{y}*.EV[AN]")):
            games.extend(parse_events(p))
        games.sort(key=lambda g: (g[1].get("date", ""), g[0]))
        # season-to-date accumulators
        P = defaultdict(lambda: defaultdict(int))      # pitcher
        PEN = defaultdict(lambda: defaultdict(int))    # team bullpen
        BAT = defaultdict(lambda: defaultdict(int))    # team batting
        RD = defaultdict(lambda: [0, 0])               # team runs for-against, games
        LG = defaultdict(int)
        PENLOG = defaultdict(list)                     # team -> [(day, {reliever: PA})]
        LAST = {}                                      # pitcher -> last day pitched
        STARTS = defaultdict(lambda: [0, 0])           # starter -> [starts, PA as starter]
        for gid, info, sp, pit, bat in games:
            vis, home = info.get("visteam"), info.get("hometeam")
            key = (gid[:3], gid[3:11], gid[11])
            if key not in scores or 0 not in sp or 1 not in sp:
                continue
            vr, hr = scores[key]
            day = datetime.strptime(info.get("date", "2000/01/01"), "%Y/%m/%d").toordinal()
            lg_pa = max(LG["PA"], 1)
            lgK, lgBB, lgFB = LG["K"] / lg_pa, (LG["BB"] + LG["HBP"]) / lg_pa, LG["FB"] / lg_pa
            hrfb = LG["HR"] / max(LG["FB"], 1)
            lw = woba(LG); lgw = lw[0] / max(lw[1], 1)

            def xfip(d, n0):
                k = rate(d, "K", lgK, n0); bbh = (d.get("BB", 0) + d.get("HBP", 0) + lgBB * n0) / (d.get("PA", 0) + n0)
                fb = rate(d, "FB", lgFB, n0)
                return 13 * fb * hrfb + 3 * bbh - 2 * k

            def wob(d, n0):
                n, den = woba(d)
                return (n + lgw * n0) / (den + n0)

            feat = {"season": y, "date": info.get("date"), "home": home, "vis": vis, "hw": int(hr > vr),
                    "total": vr + hr, "temp": info.get("temp"), "wind": info.get("windspeed"), "winddir": info.get("winddir")}
            for side, tag, team in ((1, "h", home), (0, "v", vis)):
                d = P[sp[side]]
                feat[tag + "_sp_xfip"] = xfip(d, 150)
                feat[tag + "_sp_kbb"] = rate(d, "K", lgK, 150) - (d.get("BB", 0) + lgBB * 150) / (d.get("PA", 0) + 150)
                feat[tag + "_sp_woba"] = wob(d, 300)
                feat[tag + "_sp_pa"] = d.get("PA", 0)
                feat[tag + "_pen_xfip"] = xfip(PEN[team], 300)
                feat[tag + "_bat_woba"] = wob(BAT[team], 400)
                rf, ra, g = RD[team][0], RD[team][1], max(RD[team][2] if len(RD[team]) > 2 else 0, 0)
                feat[tag + "_rd"] = (rf - ra) / (g + 10)
                # fatigue: bullpen workload in the last 1 and 3 days, relievers used both of the last 2 days
                recent = [(d0, r) for d0, r in PENLOG[team] if day - d0 <= 3]
                feat[tag + "_pen_pa3"] = sum(sum(r.values()) for d0, r in recent)
                feat[tag + "_pen_pa1"] = sum(sum(r.values()) for d0, r in recent if day - d0 == 1)
                d1 = set().union(*[r for d0, r in recent if day - d0 == 1]) if recent else set()
                d2 = set().union(*[r for d0, r in recent if day - d0 == 2]) if recent else set()
                feat[tag + "_pen_b2b"] = len(d1 & d2)
                feat[tag + "_sp_rest"] = min(day - LAST.get(sp[side], day - 10), 10)
                st = STARTS[sp[side]]
                feat[tag + "_sp_depth"] = (st[1] + 24 * 3) / (st[0] + 3)  # batters faced per start, prior 24
            if LG["PA"] > 5000:  # skip opening days with no league baseline
                rows.append(feat)
            # update after the game
            for (side, pid, starter), c in pit.items():
                team = home if side == 1 else vis
                for k, v in c.items():
                    P[pid][k] += v
                    LG[k] += v
                    if not starter:
                        PEN[team][k] += v
            for side, team in ((1, home), (0, vis)):
                rel = {pid: c.get("PA", 0) for (s2, pid, starter), c in pit.items() if s2 == side and not starter}
                PENLOG[team] = [x for x in PENLOG[team] if day - x[0] < 4] + [(day, rel)]
                STARTS[sp[side]][0] += 1
                STARTS[sp[side]][1] += sum(c.get("PA", 0) for (s2, pid, starter), c in pit.items() if s2 == side and starter)
            for (s2, pid, starter) in pit:
                LAST[pid] = day
            for side, c in bat.items():
                team = home if side == 1 else vis
                for k, v in c.items():
                    BAT[team][k] += v
            for team, rf, ra in ((home, hr, vr), (vis, vr, hr)):
                r = RD[team]
                if len(r) == 2:
                    r.append(0)
                r[0] += rf; r[1] += ra; r[2] += 1
    return rows


FEATS = ["sp_xfip", "sp_kbb", "sp_woba", "pen_xfip", "bat_woba", "rd",
         "pen_pa3", "pen_pa1", "pen_b2b", "sp_rest", "sp_depth"]
BASE_FEATS = FEATS[:6]


def xy(rows, feats=None):
    X, Y = [], []
    for r in rows:
        X.append([r["h_" + f] - r["v_" + f] for f in feats or FEATS]); Y.append(r["hw"])
    return X, Y


def fit_logistic(X, Y, iters=400, lr=0.5, l2=1e-3):
    import numpy as np
    X = np.array(X); Y = np.array(Y)
    mu, sd = X.mean(0), X.std(0) + 1e-12
    Z = np.c_[np.ones(len(X)), (X - mu) / sd]
    w = np.zeros(Z.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Z @ w))
        g = Z.T @ (p - Y) / len(Y) + l2 * np.r_[0, w[1:]]
        w -= lr * g
    return w, mu, sd


def predict(model, X):
    import numpy as np
    w, mu, sd = model
    Z = np.c_[np.ones(len(X)), (np.array(X) - mu) / sd]
    return 1 / (1 + np.exp(-Z @ w))


def logloss(p, y):
    return -sum(math.log(pi if yi else 1 - pi) for pi, yi in zip(p, y)) / len(y)


def main(root):
    years = [y for y in range(2012, 2026) if os.path.exists(os.path.join(root, str(y), f"GL{y}.TXT"))]
    rows = build(root, years)
    train = [r for r in rows if r["season"] <= 2019]
    valid = [r for r in rows if 2021 <= r["season"] <= 2022]
    test = [r for r in rows if r["season"] >= 2023]
    old = fit_logistic(*xy(train, BASE_FEATS))
    for name, part in (("valid 2021-22", valid), ("test 2023-25", test)):
        X, Y = xy(part, BASE_FEATS)
        print(f"{name} without fatigue: logloss {logloss(predict(old, X), Y):.4f}")
    model = fit_logistic(*xy(train))
    base = sum(r["hw"] for r in train) / len(train)
    print(f"games: train {len(train)}  valid {len(valid)}  test {len(test)}  home win rate {base:.3f}")
    print("weights (std units):", dict(zip(["home"] + FEATS, [round(v, 3) for v in model[0]])))
    for name, part in (("valid 2021-22", valid), ("test 2023-25", test)):
        X, Y = xy(part)
        p = predict(model, X)
        acc = sum((pi > 0.5) == yi for pi, yi in zip(p, Y)) / len(Y)
        print(f"{name}: logloss {logloss(p, Y):.4f} vs home-only {logloss([base] * len(Y), Y):.4f}  accuracy {acc:.3f}")
    return rows, model


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/home/claude/data_mlb/rs/seasons")
