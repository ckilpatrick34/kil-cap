"""The Book: a PAPER account that only bets the rules that held up on seasons the research never saw.

Recommend-only. No Kalshi account, keys or orders: entries are written to data/book.json at the price
shown plus Kalshi's taker fee, and graded when Kalshi settles the market (same machinery as AutoTrack).

Sleeves (evidence in LINE_SYSTEMS.md, unseen-season tests only):
  wind  NFL total, wind 15+ mph at kickoff, bet the under.  55.4% / +5.8% on 267 test bets.  $10.
  prime NFL Sunday/Monday night, bet the under.          53.2% / +3.3% on 491 test bets.   $5.
  gap   Any league, moneyline only: Kalshi cheaper than the de-vigged sportsbook moneyline by 3c+ after fee.
        No model beat the closing line, so the book price is our best truth estimate.  Spreads and totals
        are excluded: their "book" probability is a normal-curve guess around the line, not a price, and
        the first live run showed it badly off for NHL 5.5 totals.  Unproven: whether the odds snapshot is
        fresh.  $5 until 30+ graded bets show positive closing-line value, then $10; never more than
        $25 open at once so one stale feed cannot drain the bankroll.
One bet per game, never more open risk than cash, never more than max_bet on one bet."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .autotrack import AutoTrack, fee

ET = ZoneInfo("America/New_York")
SLEEVES = {
    "wind": {"label": "NFL wind under", "stake": 10.0, "cap": 0.54,
             "evidence": "NFL unders with 15+ mph wind: 55.4% won, +5.8% return, 267 bets on unseen seasons"},
    "prime": {"label": "NFL night-game under", "stake": 5.0, "cap": 0.52,
              "evidence": "NFL Sunday/Monday night unders: 53.2% won, +3.3% return, 491 bets on unseen seasons"},
    "gap": {"label": "Vegas gap", "stake": 5.0, "stake_proven": 10.0, "min_gap": 0.03, "max_gap": 0.12,
            "lo": 0.25, "hi": 0.85, "max_open": 25.0,
            "evidence": "Kalshi moneyline priced below the de-vigged sportsbook moneyline by 3c+ after fee. Unproven: "
                        "closing-line value on the first 30 bets decides whether it graduates to $10"},
}
ORDER = ("wind", "prime", "gap")   # stronger evidence first when one game qualifies twice


def _no(c):
    return None if not c.get("yes_bid") else round(1 - c["yes_bid"], 4)


def _title(g, c, side):
    if c["kind"] == "total":
        return f"{g['name']}: {'Over' if side == 'yes' else 'Under'} {c['line']:g}"
    team = g[c["team"]]["abbr"]
    what = f"{team} to win" if c["kind"] == "winner" else f"{team} wins by {c['line']:g}+"
    return f"{g['name']}: {what}" + ("" if side == "yes" else " NO")


def _team_margin(g, c):
    m = (g.get("book") or {}).get("margin")
    return None if m is None else (m if c["team"] == "home" else -m)


def _under(g, cap):
    """The NO side of the 'Total over X' contract closest to the book total, if priced at or below cap."""
    bt = (g.get("book") or {}).get("total")
    if bt is None:
        return None
    rows = [c for c in g.get("contracts", []) if c["kind"] == "total" and abs(c["line"] - bt) <= 1.5
            and _no(c) is not None and _no(c) <= cap]
    if not rows:
        return None
    c = min(rows, key=lambda c: (abs(c["line"] - bt), -c["line"]))
    return c, "no", _no(c)


def _prime(g) -> bool:
    try:
        t = datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone(ET)
    except (KeyError, ValueError, AttributeError):
        return False
    return t.weekday() in (6, 0) and (t.hour, t.minute) >= (19, 30)


def _gap(g, s):
    """Moneylines only: the one contract whose p_book is a real de-vigged sportsbook price."""
    if "p_home" not in (g.get("book") or {}):
        return None
    best = None
    for c in g.get("contracts", []):
        pb = c.get("p_book")
        if pb is None or c["kind"] != "winner":
            continue
        for side, fair, price in (("yes", pb, c.get("yes_ask")), ("no", 1 - pb, _no(c))):
            if not price or not s["lo"] <= price <= s["hi"]:
                continue
            gap = fair - price - 0.07 * price * (1 - price)
            if s["min_gap"] <= gap <= s["max_gap"] and (best is None or gap > best[3]):
                best = (c, side, price, gap, fair)
    return best


def candidates(games: list[dict]) -> list[dict]:
    """At most one book bet per pre-game game, from the strongest sleeve that qualifies."""
    out = []
    for g in games:
        if g.get("state") != "pre":
            continue
        nfl = g.get("league_key") == "nfl"
        wind = ((g.get("model") or {}).get("weather") or {}).get("wind_mph")
        hit = None
        for sl in ORDER:
            s = SLEEVES[sl]
            if sl == "wind" and nfl and wind is not None and wind >= 15 and (u := _under(g, s["cap"])):
                hit = (sl, *u, None, f"Wind {wind:.0f} mph at kickoff. {s['evidence']}.")
            elif sl == "prime" and nfl and _prime(g) and (u := _under(g, s["cap"])):
                hit = (sl, *u, None, f"Night game. {s['evidence']}.")
            elif sl == "gap" and (b := _gap(g, s)):
                c, side, price, gap, fair = b
                hit = (sl, c, side, price, fair, f"Sportsbook says {fair:.0%}, Kalshi asks {price:.0%} + fee "
                                                 f"(gap {gap * 100:.1f}c).")
            if hit:
                break
        if hit:
            sl, c, side, price, fair, why = hit
            out.append({"sleeve": sl, "ticker": c["ticker"], "side": side, "price": price, "fair": fair,
                        "why": why, "title": _title(g, c, side), "league": g["league"], "game_id": g["id"],
                        "kind": c["kind"], "start": g["start"], "close": c.get("close_ts")})
    return out


class Book(AutoTrack):
    def gap_proven(self) -> bool:
        clv = [b["clv"] for b in self.bets if b.get("sleeve") == "gap" and b.get("clv") is not None]
        return len(clv) >= 30 and sum(clv) / len(clv) > 0

    def _open_cost(self, sleeve: str) -> float:
        return sum(b["cost"] for b in self.bets if b.get("sleeve") == sleeve and b["result"] is None)

    def stake(self, sleeve: str) -> float:
        s = SLEEVES[sleeve]
        st = s["stake_proven"] if sleeve == "gap" and self.gap_proven() else s["stake"]
        return min(st, self.max_bet)

    def enter(self, cands: list[dict], version: str, now: float | None = None) -> int:
        import time
        now, n = now or time.time(), 0
        games = {b.get("game_id") for b in self.bets}
        for c in cands:
            if c["ticker"] in self.d["bets"] or c["game_id"] in games:
                continue
            p = c["price"]
            stake = self.stake(c["sleeve"])
            count = int(stake // p)
            while count > 0 and count * p + fee(count, p) > stake:
                count -= 1
            if count < 1:
                continue
            f = fee(count, p)
            cost = round(count * p + f, 2)
            if cost > self.cash() or cost > self.max_bet:
                continue
            cap = SLEEVES[c["sleeve"]].get("max_open")
            if cap is not None and self._open_cost(c["sleeve"]) + cost > cap:
                continue
            edge = None if c["fair"] is None else round(c["fair"] - p, 4)
            self.d["bets"][c["ticker"]] = {
                **{k: c[k] for k in ("ticker", "side", "price", "fair", "sleeve", "why", "title", "league",
                                     "game_id", "kind", "start", "close")},
                "ts": now, "count": count, "fee": f, "cost": cost, "edge": edge, "desk": "book",
                "grade": SLEEVES[c["sleeve"]]["label"], "version": version, "last_mid": p,
                "result": None, "pnl": 0.0, "clv": None}
            games.add(c["game_id"])
            n += 1
        return n

    def summary(self, now: float | None = None) -> dict:
        s = super().summary(now)
        opn = sorted((b for b in self.bets if b["result"] is None), key=lambda b: b.get("start") or "")
        s["open"] = [{k: b.get(k) for k in ("ticker", "title", "side", "price", "count", "cost", "fair", "league",
                                            "start", "ts", "sleeve", "why", "last_mid")} for b in opn]
        done = sorted((b for b in self.bets if b["result"] is not None), key=lambda b: b.get("settled", b["ts"]))
        s["recent"] = [{k: b.get(k) for k in ("ticker", "title", "side", "price", "cost", "result", "pnl", "clv",
                                              "league", "sleeve")} for b in done[-40:][::-1]]
        g: dict = {}
        for b in done:
            g.setdefault(b.get("sleeve"), []).append(b)
        s["by"]["sleeve"] = [{"key": k, **self._agg(v)} for k, v in g.items()]
        # expected value of what's open: sleeves with a tested hit rate use it, the gap sleeve uses book fair
        ev = 0.0
        for b in opn:
            p = {"wind": 0.554, "prime": 0.532}.get(b.get("sleeve"), b.get("fair") or b["price"])
            ev += b["count"] * p - b["cost"]
        s["open_ev"] = round(ev, 2)
        s["cash"] = round(self.cash(), 2)
        s["sleeves"] = {k: {**v, "stake_now": self.stake(k)} for k, v in SLEEVES.items()}
        s["gap_proven"] = self.gap_proven()
        return s

    @staticmethod
    def _agg(rows):
        st, pnl = sum(r["cost"] for r in rows), sum(r["pnl"] for r in rows)
        w = sum(r["result"] == "W" for r in rows)
        clv = [r["clv"] for r in rows if r.get("clv") is not None]
        return {"n": len(rows), "w": w, "l": len(rows) - w, "win_rate": round(w / len(rows), 3) if rows else None,
                "staked": round(st, 2), "pnl": round(pnl, 2), "roi": round(pnl / st, 3) if st else None,
                "avg_clv": round(sum(clv) / len(clv), 3) if clv else None}
