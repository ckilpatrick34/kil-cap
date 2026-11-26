"""Today's slate: games, our price vs the book vs Kalshi, and graded trade signals.

Gates before a signal is shown as tradeable:
  * our model and the de-vigged book BOTH price the contract above the Kalshi ask (agreement),
  * edge after the Kalshi taker fee >= min_edge,
  * the game hasn't started, and the contract isn't a longshot (< 15c; Kalshi longshots are overpriced).
Size = quarter-Kelly on the fee-inclusive cost x the segment multiplier (Big Vin + our own track record),
capped by max trade.  Picks are ranked by expected profit in dollars; league constants come from the
nightly learning loop (learn.py) when it has promoted a champion."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import learn
from . import model as M
from . import segments as SEG
from .espn import Espn
from .kalshi_games import all_markets, attach
from .leagues import LEAGUES
from .ratings import fit
from .track import Track
from .weather import Weather

LONGSHOT = 0.15
PRO = {"nfl", "nba", "nhl"}          # sharpest markets: demand more edge (Big Vin small edges = noise)
KIND_EXTRA = {"winner": 0.0, "spread": 0.01, "total": 0.01}
STRATEGY_ID = "game_model"


def taker_fee(p: float) -> float:
    return 0.07 * p * (1 - p)


def grade(book_agrees: bool | None, gp: int, width: float | None, volume) -> str:
    pts = 0
    pts += 2 if book_agrees else 0
    pts += 1 if gp >= 6 else 0
    pts += 1 if width is not None and width <= 0.03 else 0
    try:
        pts += 1 if float(volume) >= 500 else 0
    except (TypeError, ValueError):
        pass
    return "A" if pts >= 4 else "B" if pts >= 3 else "C"


def price_contract(lg, c: dict, mean_model: dict, mean_blend: dict, book: dict) -> dict:
    """Probability the contract's YES pays, from model / book / blend."""
    def p_of(mean):
        if not mean:
            return None
        if c["kind"] == "winner":
            p = M.p_home_win(lg, mean["margin"])
            return p if c["team"] == "home" else 1 - p
        if c["kind"] == "spread":
            if c["team"] == "home":
                return M.p_cover(mean["margin"], c["line"], lg.sigma_margin)
            return M.p_cover(-mean["margin"], c["line"], lg.sigma_margin)
        return M.p_over(mean["total"], c["line"], lg.sigma_total)
    book_mean = {k: book[k] for k in ("margin", "total") if k in book}
    pb = None
    if c["kind"] == "winner" and "p_home" in book:
        pb = book["p_home"] if c["team"] == "home" else 1 - book["p_home"]
    elif (c["kind"] == "total" and "total" in book) or (c["kind"] != "total" and "margin" in book):
        pb = p_of(book_mean)
    return {"model": p_of(mean_model), "book": pb, "fair": p_of(mean_blend)}


def best_side(c: dict, probs: dict, min_edge: float) -> dict | None:
    q, qm, qb = probs["fair"], probs["model"], probs["book"]
    if q is None:
        return None
    cands = []
    if c["yes_ask"]:
        cands.append(("yes", c["yes_ask"], q, qm, qb))
    if c["yes_bid"]:
        cands.append(("no", round(1 - c["yes_bid"], 2), 1 - q, 1 - qm if qm is not None else None,
                      1 - qb if qb is not None else None))
    best = None
    for side, price, fair, pm, pbk in cands:
        if not (0 < price < 1):
            continue
        edge = fair - price - taker_fee(price)
        if best is None or edge > best["edge"]:
            agree = None if pbk is None else (pm is not None and pm > price and pbk > price)
            best = {"side": side, "price": price, "fair": fair, "edge": edge, "book_agrees": agree,
                    "model_p": pm, "book_p": pbk}
    return best


class Slate:
    def __init__(self, public, data_dir: Path, tz: str = "America/Chicago", espn: Espn | None = None,
                 weather: Weather | None = None, leagues: list[str] | None = None):
        self.public = public
        self.dir = Path(data_dir)
        self.tz = ZoneInfo(tz)
        self.espn = espn or Espn(self.dir / "espn")
        self.weather = weather or Weather()
        self.leagues = leagues or list(LEAGUES)
        self._ratings: dict = {}
        self._lock = threading.Lock()
        self.state = {"updated": None, "games": [], "signals": [], "errors": [], "ratings_n": {}}
        self.track = Track(self.dir / "track.json")
        self.clv_path = self.dir / "clv.json"
        self.params_path = self.dir / "model_params.json"
        self.segments_path = self.dir / "segments.json"
        try:
            self.clv = json.loads(self.clv_path.read_text())
        except (OSError, ValueError):
            self.clv = {}

    # ---------- data ----------
    def ratings(self, key: str, today):
        hit = self._ratings.get(key)
        if hit and time.time() - hit[0] < 3 * 3600:
            return hit[1]
        lg, lam = learn.effective(key, learn.load(self.params_path))
        R = fit(lg, self.espn.history(lg, today), time.time(), lam=lam)
        self._ratings[key] = (time.time(), R)
        return R

    def refresh(self, min_edge: float = 0.03, equity: float = 1000.0, max_trade: float = 50.0,
                days_ahead: int = 2) -> dict:
        today = datetime.now(self.tz).date()
        games_out, signals, errors, rn = [], [], [], {}
        params, seg = learn.load(self.params_path), SEG.load_table(self.segments_path)
        for key in self.leagues:
            lg, _lam = learn.effective(key, params)
            try:
                R = self.ratings(key, today)
                rn[key] = R.n
                upcoming = []
                for d in range(days_ahead + 1):
                    upcoming += [g for g in self.espn.scoreboard(lg, today + timedelta(days=d)) if g["state"] != "post"]
                if not upcoming:
                    continue
                kal = attach(key, upcoming, all_markets(self.public, key))
            except Exception as e:  # one league failing must not blank the slate
                errors.append(f"{lg.name}: {e}")
                continue
            for g in upcoming:
                contracts = kal.get(g["id"])
                if not contracts or not any(contracts.values()):
                    continue
                summ = self.espn.summary(lg, g["id"]) if g["state"] == "pre" else {}
                wx = (self.weather.at(g["city"], g["region"], g["start_ts"])
                      if lg.outdoor and not g.get("indoor") and g["state"] == "pre" else None)
                proj = M.project(lg, g, R, summ, wx)
                if not proj:
                    continue
                book = M.book_view(lg, g["odds"])
                mean_b = M.blend(lg, proj, book)
                rows = []
                for kind in ("winner", "spread", "total"):
                    for c in contracts[kind]:
                        probs = price_contract(lg, c, proj, mean_b, book)
                        bs = best_side(c, probs, min_edge)
                        width = (c["yes_ask"] - c["yes_bid"]) if c["yes_ask"] and c["yes_bid"] else None
                        row = {**c, "p_model": probs["model"], "p_book": probs["book"], "p_fair": probs["fair"],
                               "best": bs}
                        if bs:
                            bs["fair_raw"] = bs["fair"]
                            bs["fair"] = self.track.shrink(key, kind, bs["edge"], bs["fair"])
                            bs["edge"] -= bs["fair_raw"] - bs["fair"]
                            need = min_edge + KIND_EXTRA[kind] + (0.01 if key in PRO else 0)
                            started = g["state"] != "pre"
                            ok = (not started and bs["edge"] >= need and bs["price"] >= LONGSHOT
                                  and bs["price"] <= 0.92 and bs["book_agrees"] is not False)
                            conf = grade(bs["book_agrees"], proj["games_played"], width, c["volume"])
                            sk = SEG.key(key, kind, bs["edge"], bs["price"])
                            mult = seg.get(sk, {}).get("mult", 1.0)
                            sz = SEG.size(bs["fair"], bs["price"], equity, max_trade, mult)
                            count, stake = sz["count"], sz["stake"]
                            row.update(tradeable=ok and mult > 0 and count >= 1, confidence=conf, stake=stake,
                                       count=count, roi=sz["roi"], exp_profit=sz["exp_profit"], segment=sk,
                                       segment_mult=mult)
                            if row["tradeable"]:
                                signals.append({
                                    "ticker": c["ticker"], "side": bs["side"], "price": bs["price"],
                                    "edge": round(bs["edge"], 4), "fair": round(bs["fair"], 4),
                                    "strategy_id": STRATEGY_ID, "count": count, "confidence": conf,
                                    "stake": stake, "roi": sz["roi"], "exp_profit": sz["exp_profit"],
                                    "segment": sk, "segment_mult": mult, "league": lg.name, "game_id": g["id"],
                                    "title": f"{g['name']}: {self.label(g, c)} {bs['side'].upper()}",
                                    "start": g["start"]})
                                self.track.record(signals[-1], key, kind, c.get("close_ts"))
                        rows.append(row)
                games_out.append({
                    "id": g["id"], "league": lg.name, "league_key": key, "name": g["name"], "start": g["start"],
                    "state": g["state"], "detail": g["detail"], "venue": g["venue"],
                    "home": g["home"], "away": g["away"], "odds": g["odds"], "book": book,
                    "model": {"margin": round(proj["margin"], 1), "total": round(proj["total"], 1),
                              "blend_margin": round(mean_b["margin"], 1), "blend_total": round(mean_b["total"], 1),
                              "games_played": proj["games_played"], "notes": proj["notes"],
                              "injuries": proj["injuries"], "weather": proj["weather"]},
                    "contracts": rows})
                self._track_clv(g, rows)
        self.track.grade(self.public, self.clv_for)
        signals.sort(key=lambda s: (-s["exp_profit"], -s["roi"]))   # max expected profit first
        games_out.sort(key=lambda g: g["start"] or "")
        with self._lock:
            self.state = {"updated": datetime.now(timezone.utc).isoformat(), "games": games_out,
                          "signals": signals, "errors": errors + ([self.espn.last_error] if self.espn.last_error else []),
                          "ratings_n": rn, "track": self.track.summary()}
        return self.state

    @staticmethod
    def label(g: dict, c: dict) -> str:
        if c["kind"] == "winner":
            return f"{g[c['team']]['abbr']} to win"
        if c["kind"] == "spread":
            return f"{g[c['team']]['abbr']} wins by {c['line']:g}+"
        return f"Total over {c['line']:g}"

    # ---------- closing line value ----------
    def _track_clv(self, g: dict, rows: list[dict]):
        """Remember the last pre-game Kalshi mid for every contract; CLV is judged against it."""
        if g["state"] != "pre":
            return
        changed = False
        for r in rows:
            if r["yes_bid"] is not None and r["yes_ask"] is not None:
                self.clv[r["ticker"]] = {"close_yes": round((r["yes_bid"] + r["yes_ask"]) / 2, 3), "ts": time.time()}
                changed = True
        if changed:
            try:
                self.clv_path.write_text(json.dumps(self.clv))
            except OSError:
                pass

    def clv_for(self, ticker: str, side: str, entry: float):
        c = self.clv.get(ticker)
        if not c:
            return None
        close = c["close_yes"] if side == "yes" else 1 - c["close_yes"]
        return round(close - entry, 3)

    def snapshot(self) -> dict:
        with self._lock:
            return self.state
