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
