from kil_capital import publish


class FakeSlate:
    def __init__(self, *a):
        self.track = None

    def refresh(self, **k):
        sig = lambda t, e: {"ticker": t, "title": t, "edge": e, "exp_profit": e, "fair": 0.5, "price": 0.4}
        return {"signals": [sig("OK", 0.05), sig("HUGE", 0.37)], "games": []}


class FakeUfc:
    def __init__(self, *a):
        pass

    def refresh(self, **k):
        return {"fights": [], "errors": []}


class FakeCrypto:
    def __init__(self, *a):
        pass

    def refresh(self, **k):
        return {"signals": [], "products": {}}


def test_implausible_edges_are_held_out(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "Slate", FakeSlate)
    monkeypatch.setattr(publish, "CryptoDesk", FakeCrypto)
    monkeypatch.setattr(publish, "UfcDesk", FakeUfc)
    monkeypatch.setattr(publish, "_learn_if_due", lambda *a: None)
    st = publish.build(None, tmp_path)
    assert [p["ticker"] for p in st["picks"]] == ["OK"]
    assert [p["ticker"] for p in st["suspect"]] == ["HUGE"]


def test_dump_is_browser_valid_json():
    import json
    out = publish.dump({"learn": {"params": {"tune_logloss": float("inf"), "x": [float("nan"), 1.5]}}})
    assert json.loads(out) == {"learn": {"params": {"tune_logloss": None, "x": [None, 1.5]}}}
    assert "Infinity" not in out and "NaN" not in out


def test_one_pick_per_game_and_kind():
    pk = lambda t, g: {"ticker": t, "game_id": g}
    picks = [pk("KXNBAGAME-26NOV26MILOKC-OKC", "g1"), pk("KXNBAGAME-26NOV26MILOKC-MIL", "g1"),
             pk("KXNBATOTAL-26NOV26MILOKC-220", "g1"), pk("KXNBATOTAL-26NOV26MILOKC-224", "g1"),
             pk("KXBTCD-X", None), pk("KXBTCD-Y", None)]
    assert [p["ticker"] for p in publish._one_per_game(picks)] == [
        "KXNBAGAME-26NOV26MILOKC-OKC", "KXNBATOTAL-26NOV26MILOKC-220", "KXBTCD-X", "KXBTCD-Y"]
