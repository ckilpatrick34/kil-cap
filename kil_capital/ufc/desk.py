"""UFC desk: every upcoming UFC fight gets a Vegas line, a Kil Cap line and a BET / No bet call.

Recommend-only. Sources (all public, no keys):
  * card and results: ESPN scoreboard (sports/mma/ufc), DraftKings moneylines from ESPN's odds feed
  * prices: Kalshi KXUFCFIGHT markets (they open a day or two before each card)
  * fighter history: ufcstats.com via github.com/Greco1899/scrape_ufc_stats, refreshed once a day

What the backtest says (reports/UFC_MODEL.md, fights the model never saw): the Kil Cap model picks the winner
63% of the time against Vegas's 68%, and betting its disagreements with Vegas lost about 10%. So Vegas is the
anchor: fair = 95% Vegas + 5% Kil Cap (log-odds), and a BET only shows when Kalshi sells a fighter at least
3c under that fair price after Kalshi's fee (same rule as the Book's `gap` sleeve). With no Vegas line there is
nothing to check our price against, so the call is "No bet".
"""
from __future__ import annotations

import json
import logging
import math
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from ..autotrack import fee
from ..sports.kalshi_games import fetch_series
from . import history
from .model import FightModel, devig, logit, prob_to_american

log = logging.getLogger("kil.ufc")
SB = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
ODDS = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/{e}/competitions/{c}/odds"
SERIES = "KXUFCFIGHT"
W_MODEL = 0.05          # weight on Kil Cap in the fair price (backtest: 0-10% all tie; Vegas carries it)
MIN_GAP, MAX_GAP = 0.03, 0.12   # bigger gaps are far likelier a stale price or a wrong match than a gift
LO, HI = 0.20, 0.85     # skip extreme prices: heavy dogs lost 20-46% in the backtest
STAKE = 5.0             # same as the Book's unproven gap sleeve; never above max_trade ($10)
DAYS_AHEAD = 14
BACKTEST = {  # reports/UFC_MODEL.md, test years 2021-2026 (fights no setting was picked on)
    "fights": 2351, "model_right": 0.632, "vegas_right": 0.679, "model_logloss": 0.640, "vegas_logloss": 0.597,
    "model_bets": 2046, "model_return": -0.099,
    "note": "Model alone loses to the closing line; Vegas is the anchor and bets come only from Kalshi price gaps."}


def _blend(pm: float, pv: float | None, w: float = W_MODEL) -> float:
    if pv is None:
        return pm
    z = w * logit(pm) + (1 - w) * logit(pv)
    return 1 / (1 + math.exp(-z))


def _ml(x) -> float | None:
    try:
        v = float(str(x).replace("+", ""))
        return v if abs(v) >= 100 else None
    except (TypeError, ValueError):
        return None


class UfcDesk:
    def __init__(self, public, data_dir: Path, http: httpx.Client | None = None, raw_dir: Path | None = None):
        self.public, self.dir = public, Path(data_dir) / "ufc"
        self.dir.mkdir(parents=True, exist_ok=True)
        # ~11 MB of CSVs: kept out of the persisted data dir so the state branch stays small (re-fetched per run)
        self.raw = Path(raw_dir) if raw_dir else Path(tempfile.gettempdir()) / "kil-ufc-raw"
        self.http = http or httpx.Client(timeout=30, headers={"User-Agent": "kil-capital-terminal"},
                                         follow_redirects=True)
        self.track_path = self.dir / "track.json"
        try:
            self.track = json.loads(self.track_path.read_text())
        except (OSError, ValueError):
            self.track = {"fights": {}}
        self.errors: list[str] = []

    # ---------- fighter history + model ----------
    def _history(self, today: date):
        raw = self.raw
        raw.mkdir(parents=True, exist_ok=True)
        stamp = raw / "fetched_on.txt"
        if not stamp.exists() or stamp.read_text().strip() != today.isoformat():
            try:
                for f in history.FILES:
                    r = self.http.get(history.RAW_BASE + f)
                    r.raise_for_status()
                    (raw / f).write_bytes(r.content)
                stamp.write_text(today.isoformat())
            except Exception as e:  # keep yesterday's copy
                self.errors.append(f"ufc history download: {e}")
        if not all((raw / f).exists() for f in history.FILES):
            raise RuntimeError("no UFC history on disk yet")
        bouts, tott = history.load_bouts(raw)
        rows, fighters = history.walk(bouts, tott)
        mpath = self.dir / "model.json"
        try:
            saved = json.loads(mpath.read_text())
            if saved.get("date") != today.isoformat() or saved.get("features") != list(history.FEATURES):
                raise ValueError
            model = FightModel.from_json(saved)
        except (OSError, ValueError, KeyError):
            X = [history.diff_row(pa, pb) for bt, pa, pb in rows if bt["winner"] and bt["date"].year >= 2001]
            y = [1.0 if bt["winner"] == "a" else 0.0 for bt, pa, pb in rows if bt["winner"] and bt["date"].year >= 2001]
            model = FightModel(5.0).fit(X, y)
            mpath.write_text(json.dumps({**model.to_json(), "date": today.isoformat(), "n": len(y)}))
        return model, fighters, tott, len(bouts)

    # ---------- ESPN card + DraftKings lines ----------
    def _card(self, today: date) -> list[dict]:
        end = today + timedelta(days=DAYS_AHEAD)
        try:
            r = self.http.get(SB, params={"dates": f"{today - timedelta(days=1):%Y%m%d}-{end:%Y%m%d}", "limit": 200})
            r.raise_for_status()
            events = r.json().get("events") or []
        except Exception as e:
            self.errors.append(f"ufc card: {e}")
            return []
        out = []
        for ev in events:
            for c in ev.get("competitions") or []:
                cs = sorted(c.get("competitors") or [], key=lambda x: x.get("order", 9))
                if len(cs) != 2:
                    continue
                st = (c.get("status") or {}).get("type") or {}
                side = []
                for x in cs:
                    a = x.get("athlete") or {}
                    rec = next((r.get("summary") for r in x.get("records") or [] if r.get("type") == "total"), None)
                    side.append({"id": str(x.get("id")), "name": a.get("displayName") or a.get("fullName") or "?",
                                 "record": rec, "country": (a.get("flag") or {}).get("alt"),
                                 "winner": bool(x.get("winner"))})
                out.append({"id": str(c.get("id")), "event_id": str(ev.get("id")), "event": ev.get("name"),
                            "start": c.get("date") or ev.get("date"), "wc": (c.get("type") or {}).get("abbreviation"),
                            "rounds": ((c.get("format") or {}).get("regulation") or {}).get("periods"),
                            "state": st.get("state"), "status": st.get("shortDetail") or st.get("description"),
                            "a": side[0], "b": side[1]})
        return out

    def _odds(self, f: dict) -> None:
        if f["state"] != "pre":
            return
        try:
            r = self.http.get(ODDS.format(e=f["event_id"], c=f["id"]))
            r.raise_for_status()
            items = r.json().get("items") or []
        except Exception as e:
            self._odds_fail = getattr(self, "_odds_fail", 0) + 1
            if self._odds_fail == 1:
                self.errors.append(f"ufc odds: {e}")
            return
        for it in items:
            got = {}
            for k in ("homeAthleteOdds", "awayAthleteOdds"):
                o = it.get(k) or {}
                ref = ((o.get("athlete") or {}).get("$ref") or "").split("?")[0].rstrip("/").split("/")[-1]
                cur = ((o.get("current") or {}).get("moneyLine") or {}).get("american")
                ml = _ml(cur) or _ml(o.get("moneyLine"))
                if ref and ml:
                    got[ref] = ml
            if f["a"]["id"] in got and f["b"]["id"] in got:
                f["a"]["vegas"], f["b"]["vegas"] = got[f["a"]["id"]], got[f["b"]["id"]]
                f["book_name"] = (it.get("provider") or {}).get("name")
                return

    # ---------- Kalshi ----------
    def _kalshi(self, fights: list[dict]) -> None:
        try:
            qs = fetch_series(self.public, SERIES)
        except Exception as e:
            self.errors.append(f"ufc kalshi: {e}")
            return
        by_name = {}
        for q in qs:
            by_name.setdefault(history.norm(q["sub"]), []).append(q)
        for f in fights:
            for s in ("a", "b"):
                n = history.norm(f[s]["name"])
                cands = by_name.get(n) or [q for k, v in by_name.items() for q in v
                                           if k.split()[-1:] == n.split()[-1:] and k[:1] == n[:1]]
                if len(cands) == 1 or (cands and len({q["event"] for q in cands}) == 1):
                    q = cands[0]
                    f[s].update({"ticker": q["ticker"], "yes_bid": q["yes_bid"], "yes_ask": q["yes_ask"],
                                 "kalshi_event": q["event"]})

    # ---------- the call ----------
    @staticmethod
    def call(f: dict, max_trade: float) -> dict:
        a, b = f["a"], f["b"]
        pa_v = devig(a["vegas"], b["vegas"])[0] if a.get("vegas") and b.get("vegas") else None
        pa = _blend(a["p_model"], pa_v)
        f["fair"] = {"a": round(pa, 4), "b": round(1 - pa, 4)}
        f["vegas_p"] = None if pa_v is None else {"a": round(pa_v, 4), "b": round(1 - pa_v, 4)}
        f["kil_line"] = {"a": prob_to_american(a["p_model"]), "b": prob_to_american(1 - a["p_model"])}
        best, by_side = None, {}
        for s, p in (("a", pa), ("b", 1 - pa)):
            ask = f[s].get("yes_ask")
            if not ask or ask >= 1:
                continue
            cost = ask + fee(1, ask)
            edge = p - cost
            by_side[s] = {"side": s, "price": ask, "cost": round(cost, 4), "edge": round(edge, 4), "p": p}
            if best is None or edge > best["edge"]:
                best = by_side[s]
        fav = "a" if pa >= 0.5 else "b"
        win = pa if fav == "a" else 1 - pa
        pick = {"side": fav, "name": f[fav]["name"], "win_pct": round(win, 4), "edge": None, "price": None,
                "stake": 0.0, "contracts": 0}
        if fav in by_side:   # the numbers shown belong to the side named on the card
            pick["edge"], pick["price"] = by_side[fav]["edge"], by_side[fav]["price"]
        if f["state"] != "pre":
            reason, label = "Fight started or finished", "No bet"
        elif pa_v is None:
            reason, label = "No Vegas line yet, so nothing to check our price against", "No bet"
        elif best is None:
            reason, label = "Not on Kalshi yet, so there is nowhere to place it", "No bet"
        elif best["edge"] < MIN_GAP:
            reason, label = f"Kalshi is no cheaper than the Vegas line (best gap {best['edge'] * 100:+.0f}c, need +{MIN_GAP * 100:.0f}c)", "No bet"
        elif best["edge"] > MAX_GAP:
            reason, label = "Gap too big to trust (stale price or wrong match)", "No bet"
        elif not (LO <= best["price"] <= HI):
            reason, label = "Price outside 20c-85c (long shots lost badly in the backtest)", "No bet"
        else:
            s = best["side"]
            stake = min(STAKE, max_trade)
            n = max(1, int(stake // best["cost"]))
            pick = {**pick, "side": s, "name": f[s]["name"], "win_pct": round(best["p"], 4), "contracts": n,
                    "edge": best["edge"], "price": best["price"],
                    "stake": round(n * best["cost"], 2), "ticker": f[s].get("ticker")}
            reason, label = f"Beats Vegas: {best['price'] * 100:.0f}c on Kalshi after fee vs {best['p'] * 100:.0f}c Vegas fair price", "BET"
        if label == "BET":
            conf = "High" if pick["edge"] >= 0.06 else "Medium"
        elif f["state"] != "pre":
            conf = "Live" if f["state"] == "in" else "Final"
        else:
            conf = "Lean" if win >= 0.60 else "Low"
        pick.update({"label": label, "reason": reason, "conf": conf})
        f["pick"] = pick
        return f

    # ---------- paper record ----------
    def _record(self, fights: list[dict]) -> dict:
        T = self.track.setdefault("fights", {})
        for f in fights:
            row = T.get(f["id"])
            if f["state"] == "pre":
                T[f["id"]] = {**(row or {}), "start": f["start"], "a": f["a"]["name"], "b": f["b"]["name"],
                              "model_a": f["a"]["p_model"], "vegas_a": (f.get("vegas_p") or {}).get("a"),
                              "bet": f["pick"] if f["pick"]["label"] == "BET" else (row or {}).get("bet")}
            elif row and row.get("result") is None and f["state"] == "post":
                w = "a" if f["a"]["winner"] else "b" if f["b"]["winner"] else None
                row["result"] = w or "draw"
                bet = row.get("bet")
                if bet and w:
                    won = bet["side"] == w
                    row["pl"] = round(bet["contracts"] - bet["stake"] if won else -bet["stake"], 2)   # $1 per winning contract
        done = [r for r in T.values() if r.get("result") in ("a", "b")]
        def right(key):
            rows = [r for r in done if r.get(key) is not None]
            return {"n": len(rows), "right": sum((r[key] >= 0.5) == (r["result"] == "a") for r in rows)}
        bets = [r for r in done if r.get("bet")]
        cut = time.time() - 120 * 86400
        self.track["fights"] = {k: v for k, v in T.items()
                                if not v.get("start") or datetime.fromisoformat(v["start"].replace("Z", "+00:00")).timestamp() > cut}
        try:
            self.track_path.write_text(json.dumps(self.track))
        except OSError as e:
            self.errors.append(f"ufc track save: {e}")
        return {"model": right("model_a"), "vegas": right("vegas_a"),
                "bets": {"n": len(bets), "won": sum(1 for r in bets if r.get("pl", 0) > 0),
                         "pl": round(sum(r.get("pl", 0) for r in bets), 2),
                         "staked": round(sum(r["bet"]["stake"] for r in bets), 2)}}

    def refresh(self, max_trade: float = 10.0, today: date | None = None) -> dict:
        today = today or datetime.now(timezone.utc).date()
        self.errors, self._odds_fail = [], 0
        try:
            model, fighters, tott, n_hist = self._history(today)
        except Exception as e:
            return {"fights": [], "errors": [f"ufc: {e}"], "backtest": BACKTEST}
        fights = self._card(today)
        for f in fights:
            self._odds(f)
            on = datetime.fromisoformat(f["start"].replace("Z", "+00:00")).date() if f.get("start") else today
            prof = {}
            for s in ("a", "b"):
                k = history.norm(f[s]["name"])
                fi = fighters.get(k) or history.Fighter()
                prof[s] = history.profile(fi, tott.get(k, {}), on)
                f[s]["ufc_fights"] = fi.n
                f[s]["ufc_record"] = f"{fi.wins}-{fi.losses}" if fi.n else "UFC debut"
                f[s]["age"] = None if prof[s]["age"] is None else round(prof[s]["age"], 1)
                f[s]["reach"] = prof[s]["reach"]
                f[s]["elo"] = round(fi.elo)
            p = float(model.prob([history.diff_row(prof["a"], prof["b"])])[0])
            f["a"]["p_model"], f["b"]["p_model"] = round(p, 4), round(1 - p, 4)
        self._kalshi(fights)
        for f in fights:
            self.call(f, max_trade)
        rec = self._record(fights)
        fights.sort(key=lambda f: (f.get("start") or "", f["id"]))
        return {"fights": fights, "record": rec, "backtest": BACKTEST, "history_fights": n_hist,
                "rules": {"w_model": W_MODEL, "min_gap": MIN_GAP, "max_gap": MAX_GAP, "stake": STAKE, "lo": LO, "hi": HI},
                "errors": self.errors}
