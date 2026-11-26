import pytest

from kil_capital.core import blocklist as bl


@pytest.mark.parametrize("text", [
    "Mississippi State at Ole Miss", "KXNCAAFGAME-26NOV28MSSTOLE", "MSU Bulldogs vs Georgia",
    "Michigan State at Ohio State", "Missouri State Bears vs Drake", "Lakers at Celtics",
])
def test_nothing_blocked_since_msu_block_lifted(text):
    assert not bl.is_blocked(text)
    assert bl.filter_markets([{"ticker": "X", "title": text}]) != []


def test_blocklist_still_works_when_a_term_is_added(monkeypatch):
    monkeypatch.setattr(bl, "ALWAYS_BLOCKED", ("egg bowl",))
    assert bl.is_blocked({"ticker": "X", "legs": [{"title": "Egg Bowl winner"}]})
    assert not bl.is_blocked("Iron Bowl")
