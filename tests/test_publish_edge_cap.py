from kil_capital import publish


class FakeSlate:
    def __init__(self, *a):
        self.track = None

    def refresh(self, **k):
        sig = lambda t, e: {"ticker": t, "title": t, "edge": e, "exp_profit": e, "fair": 0.5, "price": 0.4}
        return {"signals": [sig("OK", 0.05), sig("HUGE", 0.37)], "games": []}


class FakeCrypto:
    def __init__(self, *a):
        pass

    def refresh(self, **k):
        return {"signals": [], "products": {}}


def test_implausible_edges_are_held_out(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "Slate", FakeSlate)
    monkeypatch.setattr(publish, "CryptoDesk", FakeCrypto)
    monkeypatch.setattr(publish, "_learn_if_due", lambda *a: None)
    st = publish.build(None, tmp_path)
    assert [p["ticker"] for p in st["picks"]] == ["OK"]
    assert [p["ticker"] for p in st["suspect"]] == ["HUGE"]


def test_dump_is_browser_valid_json():
    import json
    out = publish.dump({"learn": {"params": {"tune_logloss": float("inf"), "x": [float("nan"), 1.5]}}})
    assert json.loads(out) == {"learn": {"params": {"tune_logloss": None, "x": [None, 1.5]}}}
    assert "Infinity" not in out and "NaN" not in out
