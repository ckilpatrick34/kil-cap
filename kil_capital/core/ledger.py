"""SQLite ledger + append-only, hash-chained audit log (spec v4 §8.2)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from decimal import Decimal
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
  client_order_id TEXT PRIMARY KEY, ts REAL, ticker TEXT, event_ticker TEXT, series_ticker TEXT,
  desk TEXT, category TEXT, league TEXT, asset TEXT, strategy_id TEXT, source TEXT,
  side TEXT, action TEXT, price TEXT, count INTEGER, tif TEXT, post_only INTEGER,
  status TEXT, kalshi_order_id TEXT, reason TEXT, max_loss TEXT, fee_est TEXT, filled INTEGER DEFAULT 0,
  model_version TEXT, signal_id TEXT
);
CREATE TABLE IF NOT EXISTS fills (
  fill_id TEXT PRIMARY KEY, client_order_id TEXT, kalshi_order_id TEXT, ts REAL, ticker TEXT,
  event_ticker TEXT, series_ticker TEXT, desk TEXT, category TEXT, league TEXT, asset TEXT,
  strategy_id TEXT, source TEXT, side TEXT, action TEXT, price TEXT, count INTEGER, fee TEXT,
  liquidity TEXT, clv_ref_price TEXT, clv_cents TEXT, markout_1m TEXT, markout_5m TEXT
);
CREATE TABLE IF NOT EXISTS settlements (
  ticker TEXT PRIMARY KEY, result TEXT, ts REAL, settlement_value TEXT, payout TEXT
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, actor TEXT, action TEXT, payload TEXT,
  result TEXT, prev_hash TEXT, hash TEXT
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TABLE IF NOT EXISTS nav_marks (
  day TEXT PRIMARY KEY, start_nav TEXT, peak_nav TEXT
);
CREATE TABLE IF NOT EXISTS nav_snapshots (ts REAL, nav TEXT);
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, strategy_id TEXT, ticker TEXT, side TEXT,
  price TEXT, fair TEXT, features TEXT, desk TEXT
);
CREATE TABLE IF NOT EXISTS backtest_runs (
  run_id TEXT PRIMARY KEY, ts REAL, strategy_id TEXT, version TEXT, data_hash TEXT,
  git_hash TEXT, config_hash TEXT, folds INTEGER, verdict TEXT
);
CREATE TABLE IF NOT EXISTS tests_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, strategy_id TEXT, variant TEXT, params TEXT,
  n_events INTEGER, roi TEXT, p_value REAL
);
CREATE TABLE IF NOT EXISTS pm_picks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, client_order_id TEXT, ticker TEXT, side TEXT,
  price TEXT, q TEXT, tag TEXT, thesis TEXT, league TEXT, close_price TEXT, result TEXT
);
"""

GENESIS = "0" * 64


def _default(o):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, Path):
        return str(o)
    return repr(o)


def canon(payload) -> str:
    return json.dumps(payload, sort_keys=True, default=_default, separators=(",", ":"))


class Ledger:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---- audit ---------------------------------------------------------------------
    def audit(self, action: str, actor: str, payload, result: str) -> str:
        with self._lock:
            row = self.db.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
            prev = row["hash"] if row else GENESIS
            ts = time.time()
            body = canon({"ts": ts, "actor": actor, "action": action, "payload": payload,
                          "result": result, "prev": prev})
            h = hashlib.sha256(body.encode()).hexdigest()
            self.db.execute(
                "INSERT INTO audit(ts, actor, action, payload, result, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
                (ts, actor, action, canon(payload), result, prev, h))
            return h

    def verify_chain(self) -> tuple[bool, int | None]:
        prev = GENESIS
        for r in self.db.execute("SELECT * FROM audit ORDER BY id"):
            body = canon({"ts": r["ts"], "actor": r["actor"], "action": r["action"],
                          "payload": json.loads(r["payload"]), "result": r["result"], "prev": prev})
            if r["prev_hash"] != prev or hashlib.sha256(body.encode()).hexdigest() != r["hash"]:
                return False, r["id"]
            prev = r["hash"]
        return True, None

    def audit_rows(self, limit=200):
        return [dict(r) for r in self.db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]

    # ---- orders / fills ------------------------------------------------------------
    def insert_order(self, o: dict):
        cols = ",".join(o)
        q = ",".join("?" for _ in o)
        with self._lock:
            self.db.execute(f"INSERT OR REPLACE INTO orders({cols}) VALUES ({q})",
                            [str(v) if isinstance(v, Decimal) else v for v in o.values()])

    def update_order(self, coid: str, **kw):
        sets = ",".join(f"{k}=?" for k in kw)
        with self._lock:
            self.db.execute(f"UPDATE orders SET {sets} WHERE client_order_id=?",
                            [str(v) if isinstance(v, Decimal) else v for v in kw.values()] + [coid])

    def get_order(self, coid: str):
        r = self.db.execute("SELECT * FROM orders WHERE client_order_id=?", (coid,)).fetchone()
        return dict(r) if r else None

    def orders(self, status: str | None = None, limit=500):
        if status:
            rows = self.db.execute("SELECT * FROM orders WHERE status=? ORDER BY ts DESC LIMIT ?", (status, limit))
        else:
            rows = self.db.execute("SELECT * FROM orders ORDER BY ts DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def insert_fill(self, f: dict):
        cols = ",".join(f)
        q = ",".join("?" for _ in f)
        with self._lock:
            self.db.execute(f"INSERT OR IGNORE INTO fills({cols}) VALUES ({q})",
                            [str(v) if isinstance(v, Decimal) else v for v in f.values()])

    def fills(self, limit=1000, since: float | None = None):
        if since is not None:
            rows = self.db.execute("SELECT * FROM fills WHERE ts>=? ORDER BY ts DESC LIMIT ?", (since, limit))
        else:
            rows = self.db.execute("SELECT * FROM fills ORDER BY ts DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def settle(self, ticker: str, result: str, value=None, payout=None):
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO settlements VALUES (?,?,?,?,?)",
                            (ticker, result, time.time(), str(value) if value is not None else None,
                             str(payout) if payout is not None else None))

    def settlements(self):
        return {r["ticker"]: dict(r) for r in self.db.execute("SELECT * FROM settlements")}

    # ---- NAV -----------------------------------------------------------------------
    def nav_mark(self, day: str, nav: Decimal) -> tuple[Decimal, Decimal]:
        """Record start-of-day NAV (first mark of the day) and running peak. Returns (start, peak)."""
        with self._lock:
            r = self.db.execute("SELECT * FROM nav_marks WHERE day=?", (day,)).fetchone()
            prev_peak = self.db.execute("SELECT peak_nav FROM nav_marks ORDER BY day DESC LIMIT 1").fetchone()
            peak = max(Decimal(prev_peak["peak_nav"]) if prev_peak else nav, nav)
            if r:
                start = Decimal(r["start_nav"])
                self.db.execute("UPDATE nav_marks SET peak_nav=? WHERE day=?", (str(peak), day))
            else:
                start = nav
                self.db.execute("INSERT INTO nav_marks VALUES (?,?,?)", (day, str(nav), str(peak)))
            self.db.execute("INSERT INTO nav_snapshots VALUES (?,?)", (time.time(), str(nav)))
            return start, peak

    def nav_history(self, limit=2000):
        return [dict(r) for r in self.db.execute("SELECT * FROM nav_snapshots ORDER BY ts DESC LIMIT ?", (limit,))]

    # ---- signals / research ---------------------------------------------------------
    def record_signal(self, sid, ticker, side, price, fair, features, desk):
        with self._lock:
            self.db.execute("INSERT INTO signals(ts,strategy_id,ticker,side,price,fair,features,desk) VALUES (?,?,?,?,?,?,?,?)",
                            (time.time(), sid, ticker, side, str(price), None if fair is None else str(fair),
                             canon(features or {}), desk))

    def signals(self, sid: str, limit=200):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM signals WHERE strategy_id=? ORDER BY ts DESC LIMIT ?", (sid, limit))]

    def record_backtest_run(self, **kw):
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO backtest_runs VALUES (?,?,?,?,?,?,?,?,?)",
                            (kw["run_id"], time.time(), kw["strategy_id"], kw.get("version"), kw.get("data_hash"),
                             kw.get("git_hash"), kw.get("config_hash"), kw.get("folds"), kw.get("verdict")))

    def record_variant(self, sid, variant, params, n_events, roi, p_value):
        with self._lock:
            self.db.execute("INSERT INTO tests_ledger(ts,strategy_id,variant,params,n_events,roi,p_value) VALUES (?,?,?,?,?,?,?)",
                            (time.time(), sid, variant, canon(params), n_events, str(roi), p_value))

    def variants_tried(self, sid) -> int:
        return self.db.execute("SELECT COUNT(*) c FROM tests_ledger WHERE strategy_id=?", (sid,)).fetchone()["c"]

    # ---- PM picks -------------------------------------------------------------------
    def add_pick(self, **kw):
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO pm_picks(ts,client_order_id,ticker,side,price,q,tag,thesis,league) VALUES (?,?,?,?,?,?,?,?,?)",
                (time.time(), kw.get("client_order_id"), kw["ticker"], kw["side"], str(kw["price"]),
                 None if kw.get("q") is None else str(kw["q"]), kw.get("tag"), kw.get("thesis"), kw.get("league")))
            return cur.lastrowid

    def picks(self, limit=500):
        return [dict(r) for r in self.db.execute("SELECT * FROM pm_picks ORDER BY ts DESC LIMIT ?", (limit,))]
