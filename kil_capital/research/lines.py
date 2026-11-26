"""Closing-line systems: rules sharp and public bettors actually use, written down before looking, graded at -110.

Each rule picks a side per game from information known at bet time (except the CLV ceiling, which is labelled).
Seasons are split in half: the first half shows whether the rule ever worked, the second half is the test.
A rule passes only if BOTH halves beat 52.4% (the -110 break-even) and the test half has 100+ bets.
Run: python -m kil_capital.research.lines   (uses the same data/raw sources as research.deep)."""
from __future__ import annotations

import math
from pathlib import Path

from kil_capital.research.deep import load

BE = 110 / 210  # break-even win rate at -110


def _margin(r):
    return r["hs"] - r["as_"]


def ats(r, side, line_key="spread"):
    """side +1 = home, -1 = away. Spread is the expected home margin. Returns 1 win, 0 loss, None push/no line."""
    ln = r.get(line_key)
    if ln is None:
        return None
    d = (_margin(r) - ln) * side
    return None if d == 0 else int(d > 0)


def ou(r, side, line_key="total"):
    """side +1 = over, -1 = under."""
    ln = r.get(line_key)
    if not ln:
        return None
    d = (r["hs"] + r["as_"] - ln) * side
    return None if d == 0 else int(d > 0)


def _move(r, k):
    a, b = r.get(k), r.get(k + "_open")
    return None if a is None or b is None else a - b


def systems(lg):
    T = {"nfl": 1.5, "cfb": 2.0, "nba": 1.5, "nhl": 0.5}.get(lg, 1.5)   # meaningful move per sport
    TT = {"cfb": 2.0, "nba": 2.0, "nhl": 0.5, "nfl": 1.5}.get(lg, 1.5)
    S = {}
    # line movement (needs opening lines: CFB, NBA spreads; CFB, NBA, NHL totals)
    S["spread: follow the move (bet close)"] = lambda r: (
        ats(r, 1 if _move(r, "spread") > 0 else -1) if _move(r, "spread") is not None and abs(_move(r, "spread")) >= T else None)
    S["spread: fade the move (bet close)"] = lambda r: (
        ats(r, -1 if _move(r, "spread") > 0 else 1) if _move(r, "spread") is not None and abs(_move(r, "spread")) >= T else None)
    S["total: follow the move (bet close)"] = lambda r: (
        ou(r, 1 if _move(r, "total") > 0 else -1) if _move(r, "total") is not None and abs(_move(r, "total")) >= TT else None)
    S["total: fade the move (bet close)"] = lambda r: (
        ou(r, -1 if _move(r, "total") > 0 else 1) if _move(r, "total") is not None and abs(_move(r, "total")) >= TT else None)
    S["CEILING spread: bet open the way it later moved"] = lambda r: (
        ats(r, 1 if _move(r, "spread") > 0 else -1, "spread_open") if _move(r, "spread") and abs(_move(r, "spread")) >= T else None)
    S["CEILING total: bet open the way it later moved"] = lambda r: (
        ou(r, 1 if _move(r, "total") > 0 else -1, "total_open") if _move(r, "total") and abs(_move(r, "total")) >= TT else None)
    # favourites / dogs
    S["home dog"] = lambda r: ats(r, 1) if r.get("spread") is not None and r["spread"] < 0 and not r["neutral"] else None
    S["road favourite fade (bet home dog 3+)"] = lambda r: ats(r, 1) if r.get("spread") is not None and r["spread"] <= -3 and not r["neutral"] else None
    S["big dog 10+"] = lambda r: ats(r, -1 if r["spread"] > 0 else 1) if r.get("spread") is not None and abs(r["spread"]) >= 10 else None
    if lg in ("nfl", "cfb"):
        S["key number: dog at exactly +3"] = lambda r: ats(r, -1 if r["spread"] > 0 else 1) if r.get("spread") is not None and abs(r["spread"]) == 3 else None
        S["key number: dog at exactly +7"] = lambda r: ats(r, -1 if r["spread"] > 0 else 1) if r.get("spread") is not None and abs(r["spread"]) == 7 else None
        S["key number: favourite at -2.5"] = lambda r: ats(r, 1 if r["spread"] > 0 else -1) if r.get("spread") is not None and abs(r["spread"]) == 2.5 else None
        S["key number: dog at +3.5"] = lambda r: ats(r, -1 if r["spread"] > 0 else 1) if r.get("spread") is not None and abs(r["spread"]) == 3.5 else None
    if lg == "nfl":
        S["wind 15+ mph: under"] = lambda r: ou(r, -1) if (r.get("wind") or 0) >= 15 and not r["dome"] else None
        S["wind 20+ mph: under"] = lambda r: ou(r, -1) if (r.get("wind") or 0) >= 20 and not r["dome"] else None
        S["cold 25F or less: under"] = lambda r: ou(r, -1) if r.get("temp") is not None and r["temp"] <= 25 and not r["dome"] else None
        S["divisional dog"] = lambda r: ats(r, -1 if r["spread"] > 0 else 1) if r.get("spread") and r.get("div") else None
        S["playoff under"] = lambda r: ou(r, -1) if r.get("playoff") else None
    S["high total: under (top 10% of totals)"] = "HIGH"
    S["low total: over (bottom 10% of totals)"] = "LOW"
    return S


def grade(results):
    w = sum(results)
    n = len(results)
    if not n:
        return {"n": 0}
    p = w / n
    z = (w - n * BE) / math.sqrt(n * BE * (1 - BE))
    return {"n": n, "win": p, "roi": p * (100 / 110) - (1 - p), "z": z}


def run(lg):
    rows = load(lg, Path("data/raw"))
    seasons = sorted({r["season"] for r in rows if r.get("spread") is not None or r.get("total")})
    mid = seasons[len(seasons) // 2]
    tots = sorted(r["total"] for r in rows if r.get("total"))
    hi, lo = (tots[int(len(tots) * 0.9)], tots[int(len(tots) * 0.1)]) if tots else (None, None)
    out = []
    for name, f in systems(lg).items():
        if f == "HIGH":
            f = lambda r: ou(r, -1) if r.get("total") and r["total"] >= hi else None
        elif f == "LOW":
            f = lambda r: ou(r, 1) if r.get("total") and r["total"] <= lo else None
        half = {"first": [], "test": []}
        for r in rows:
            try:
                x = f(r)
            except (TypeError, KeyError):
                x = None
            if x is not None:
                half["test" if r["season"] >= mid else "first"].append(x)
        a, b = grade(half["first"]), grade(half["test"])
        if a["n"] == 0 and b["n"] == 0:
            continue
        ok = a["n"] and b["n"] >= 100 and a["win"] > BE and b["win"] > BE and not name.startswith("CEILING")
        out.append({"league": lg, "system": name, "first": a, "test": b, "pass": bool(ok),
                    "split": f"{seasons[0]}-{mid - 1} / {mid}-{seasons[-1]}"})
    return out


def fmt(g):
    return "-" if not g["n"] else f"{g['win']:.1%} on {g['n']} ({g['roi']:+.1%})"


def main():
    allr = []
    for lg in ("nfl", "cfb", "nba", "nhl"):
        allr += run(lg)
    L = ["# Closing-line systems, graded at -110 (break-even 52.4%)", "",
         "First half = did it ever work. Test half = later seasons. PASS needs both halves above 52.4% and 100+ test bets.",
         "CEILING rows use the future line move and are not bettable; they show what predicting moves would be worth.", "",
         "| league | system | seasons | first half | test half | test z | pass |", "|---|---|---|---|---|---|---|"]
    for r in allr:
        z = f"{r['test']['z']:+.1f}" if r["test"]["n"] else "-"
        L.append(f"| {r['league']} | {r['system']} | {r['split']} | {fmt(r['first'])} | {fmt(r['test'])} | {z} | {'PASS' if r['pass'] else ''} |")
    n = sum(not r["system"].startswith("CEILING") for r in allr)
    L += ["", f"{n} systems tested. At 5% significance about {n * 0.05:.0f} would look good by luck alone, so a PASS "
          "with test z under 2 is weak evidence."]
    L += ["", "## Simple scoring model vs the OPENING total (bet the open, -110)", "",
          "| league | seasons | gap k (chosen on first half) | first half | test half | line moved our way |", "|---|---|---|---|---|---|"]
    for lg in ("nba", "nhl", "cfb"):
        e = early_totals(lg)
        L.append(f"| {lg} | {e['split']} | {e['k']} | {fmt(e['first'])} | {fmt(e['test'])} | {e['test']['clv']:.0%} |")
    txt = "\n".join(L)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/LINE_SYSTEMS.md").write_text(txt)
    print(txt)



# ---- Beating the opener: a simple point-in-time scoring model vs the OPENING total -----------------------------
def early_totals(lg, alpha=0.08):
    """EWMA points-for/against per team (updated only after each game) -> expected total.  Bet at the open when the
    model disagrees with it by >= k; k is chosen on the first half of seasons, reported on the second half.
    Also reports how often the line then moved our way (closing-line value)."""
    rows = sorted(load(lg, Path("data/raw")), key=lambda r: (r["ts"], r["id"]))
    off, de, avg = {}, {}, None
    picks = []
    for r in rows:
        h, a = r["home"], r["away"]
        if avg is not None and all(t in off for t in (h, a)) and r.get("total_open"):
            pred = (off[h] + de[a] + off[a] + de[h]) / 2
            picks.append((r, pred - r["total_open"]))
        tot = r["hs"] + r["as_"]
        avg = tot / 2 if avg is None else avg + 0.01 * (tot / 2 - avg)
        for t, pf, pa in ((h, r["hs"], r["as_"]), (a, r["as_"], r["hs"])):
            off[t] = off.get(t, avg) + alpha * (pf - off.get(t, avg))
            de[t] = de.get(t, avg) + alpha * (pa - de.get(t, avg))
    seasons = sorted({r["season"] for r, _ in picks})
    mid = seasons[len(seasons) // 2]
    sd = (sum(e * e for _, e in picks) / len(picks)) ** 0.5
    def res(sel, k):
        out, clv = [], []
        for r, e in sel:
            if abs(e) < k:
                continue
            x = ou(r, 1 if e > 0 else -1, "total_open")
            if x is not None:
                out.append(x)
            mv = _move(r, "total")
            if mv:
                clv.append(int((mv > 0) == (e > 0)))
        g = grade(out)
        g["clv"] = sum(clv) / len(clv) if clv else None
        return g
    first = [p for p in picks if p[0]["season"] < mid]
    test = [p for p in picks if p[0]["season"] >= mid]
    ks = [round(sd * f, 1) for f in (0.25, 0.5, 0.75, 1.0)]
    best = max(ks, key=lambda k: (res(first, k)["roi"] if res(first, k)["n"] >= 100 else -9))
    return {"league": lg, "k_options": ks, "k": best, "first": res(first, best), "test": res(test, best),
            "split": f"{seasons[0]}-{mid - 1} / {mid}-{seasons[-1]}",
            "all_k_test": {k: res(test, k) for k in ks}}



if __name__ == "__main__":
    main()
