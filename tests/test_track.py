import time

from kil_capital.sports.track import Track, edge_bucket


class Pub:
    def __init__(self, res): self.res = res
    def market(self, t): return {"result": self.res[t]}


def sig(t, edge=0.06, fair=0.6, price=0.5):
    return {"ticker": t, "side": "yes", "price": price, "fair": fair, "edge": edge}


def test_bucket_edges():
    assert edge_bucket(0.03) == "3-5c" and edge_bucket(0.07) == "5-10c" and edge_bucket(0.2) == "10c+"


def test_record_once_grade_and_summary(tmp_path):
    tr = Track(tmp_path / "t.json")
    tr.record(sig("A"), "ncaaf", "spread", 0)
    tr.record(sig("A", edge=0.5), "ncaaf", "spread", 0)     # duplicate ignored
    tr.record(sig("B"), "ncaaf", "spread", 0)
    tr.grade(Pub({"A": "yes", "B": "no"}))
    s = tr.summary()
    assert s["total"]["graded"] == 2 and s["total"]["wins"] == 1
    assert Track(tmp_path / "t.json").summary()["total"]["graded"] == 2   # persisted


def test_pending_not_graded_before_close(tmp_path):
    tr = Track(tmp_path / "t.json")
    tr.record(sig("A"), "nba", "winner", 9e12)
    tr.grade(Pub({"A": "yes"}))
    assert tr.summary()["total"]["pending"] == 1


def test_shrink_pulls_overconfident_bucket_down(tmp_path):
    tr = Track(tmp_path / "t.json")
    assert tr.shrink("nba", "spread", 0.06, 0.60) == 0.60       # no data -> unchanged
    for i in range(40):                                          # fair 0.60, hit 25%
        tr.record(sig(f"T{i}"), "nba", "spread", 0)
    tr.grade(Pub({f"T{i}": ("yes" if i % 4 == 0 else "no") for i in range(40)}))
    f = tr.shrink("nba", "spread", 0.06, 0.60)
    assert 0.45 < f < 0.60                                       # pulled toward 0.25, partially
    assert tr.shrink("nba", "total", 0.06, 0.60) == 0.60        # other buckets untouched



class FakePublic:
    def __init__(self, results):
        self.results, self.calls = results, []

    def market(self, t):
        self.calls.append(t)
        return {"result": self.results.get(t, "")}


def _sig(t, start):
    return {"ticker": t, "side": "yes", "price": 0.4, "fair": 0.5, "edge": 0.06, "start": start}


def test_grades_after_game_even_when_close_time_is_days_away(tmp_path):
    now = time.time()
    tr = Track(tmp_path / "t.json")
    tr.record(_sig("A", "2026-01-01T00:00:00Z"), "nba", "ml", "2099-01-01T00:00:00Z")   # game long over
    tr.record(_sig("B", "2099-01-01T00:00:00Z"), "nba", "ml", "2099-01-03T00:00:00Z")   # not played yet
    pub = FakePublic({"A": "yes", "B": "no"})
    tr.grade(pub, now=now)
    assert pub.calls == ["A"]
    assert tr.rows["A:yes"]["result"] == "W"
    assert tr.rows["B:yes"]["result"] is None
    assert Track(tmp_path / "t.json").rows["A:yes"]["result"] == "W"   # persisted


def test_unsettled_rows_rotate_instead_of_blocking(tmp_path):
    now = time.time()
    tr = Track(tmp_path / "t.json")
    for i in range(5):
        tr.record(_sig(f"T{i}", "2026-01-01T00:00:00Z"), "nba", "ml", None)
    pub = FakePublic({"T4": "no"})
    tr.grade(pub, max_calls=2, now=now)
    tr.grade(pub, max_calls=2, now=now + 2000)
    tr.grade(pub, max_calls=2, now=now + 4000)
    assert "T4" in pub.calls and tr.rows["T4:yes"]["result"] == "L"
