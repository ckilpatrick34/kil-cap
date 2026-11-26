import time
from kil_capital.sports.track import Track


class _Pub:
    def market(self, t):
        return {"result": "yes"}


def test_grade_handles_iso_string_close_ts(tmp_path):
    tr = Track(tmp_path / "t.json")
    tr.rows["X:yes"] = {"ticker": "X", "side": "yes", "price": 0.4, "fair": 0.5, "edge": 0.06, "league": "nfl",
                        "kind": "winner", "bucket": "5-10c", "title": "", "close_ts": "2020-01-01T00:00:00Z",
                        "logged": time.time(), "result": None}
    tr.grade(_Pub())
    assert tr.rows["X:yes"]["result"] == "W"
