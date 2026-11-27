import gzip
import json

from kil_capital.research.recorder import Recorder

NOW = 1_800_000_000


class FakePublic:
    def __init__(self):
        self.calls = []
        self.markets = [
            {"ticker": "KXNBA-A", "yes_bid_dollars": "0.04", "yes_ask_dollars": "0.06", "close_time": "2027-01-15T10:00:00Z"},
            {"ticker": "KXNBA-B", "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.42", "close_time": "2027-01-15T10:00:00Z"},
            {"ticker": "KXBTCD-X", "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.45", "close_time": "2027-01-15T10:00:00Z"},
            {"ticker": "KXMVE-Z", "yes_bid_dollars": "0.01", "yes_ask_dollars": "0.02", "close_time": "2027-01-15T10:00:00Z"},
        ]
        self.result = None

    def get(self, path, params=None, ttl=None):
        self.calls.append(path)
        if path == "/markets" and "tickers" in params:
            return {"markets": [{"ticker": t, "result": self.result, "status": "settled"}
                                for t in params["tickers"].split(",")] if self.result else []}
        if path == "/markets":
            return {"markets": self.markets}
        if path == "/markets/trades":
            return {"trades": [
                {"trade_id": "1", "ticker": "KXNBA-A", "yes_price_dollars": "0.06", "count": 50, "taker_side": "yes",
                 "created_time": "2027-01-15T09:00:00Z"},
                {"trade_id": "2", "ticker": "KXNBA-B", "yes_price_dollars": "0.41", "count": 5, "taker_side": "no",
                 "created_time": "2027-01-15T09:00:01Z"}]}
        if path == "/incentive_programs":
            raise RuntimeError("404")
        raise AssertionError(path)

    def orderbook(self, t, depth=5):
        return {"yes": [[4, 100]], "no": [[94, 300]]}

    def series(self, s):
        return {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1, "category": "Sports"}


def rows(root, stream):
    out = []
    for f in sorted((root / "recorders").glob(f"*/{stream}.jsonl.gz")):
        with gzip.open(f, "rt") as fh:
            out += [json.loads(line) for line in fh]
    return out


def test_records_tails_and_crypto_only_and_dedupes(tmp_path):
    pub = FakePublic()
    st = Recorder(pub, tmp_path).run(now=NOW)
    q = rows(tmp_path, "quotes")
    assert {r["t"] for r in q} == {"KXNBA-A", "KXBTCD-X"} and q[0]["a"] in (6, 45)
    assert [r["t"] for r in rows(tmp_path, "tape")] == ["KXNBA-A"]          # untracked mid-priced market dropped
    assert rows(tmp_path, "tape")[0] == {"ts": rows(tmp_path, "tape")[0]["ts"], "t": "KXNBA-A", "p": 6, "n": 50,
                                         "s": "yes", "id": "1"}
    assert [r["t"] for r in rows(tmp_path, "books")] == ["KXNBA-A"]
    assert rows(tmp_path, "fees")[0]["fee_type"] == "quadratic_with_maker_fees"
    assert st["incentives"].startswith("unavailable") and st["mode"].startswith("RECORD-ONLY")

    Recorder(pub, tmp_path).run(now=NOW + 150)                               # nothing changed: no new rows
    assert len(rows(tmp_path, "quotes")) == 2 and len(rows(tmp_path, "tape")) == 1
    assert len(rows(tmp_path, "books")) == 1


def test_settles_after_close_and_stops_tracking(tmp_path):
    pub = FakePublic()
    Recorder(pub, tmp_path).run(now=NOW)
    pub.markets, pub.result = [], "no"
    close = 1_800_000_000 + 10 ** 8                                          # far beyond close_time
    st = Recorder(pub, tmp_path).run(now=close)
    assert {r["t"]: r["result"] for r in rows(tmp_path, "settle")} == {"KXNBA-A": "no", "KXBTCD-X": "no"}
    assert st["tracking"] == 0
