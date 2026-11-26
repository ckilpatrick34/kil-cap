import pytest

from kil_capital.core import blocklist as bl


@pytest.mark.parametrize("text", [
    "Mississippi State at Ole Miss", "Will Mississippi St. win?", "Miss St vs Alabama", "Miss. State Bulldogs",
    "MS State", "Egg Bowl winner", "Games in Starkville", "Hail State", "Davis Wade Stadium", "Dudy Noble Field",
    "MSU Bulldogs vs Georgia", "MSU vs Ole Miss", "KXNCAAFGAME-26NOV28MSSTOLE", "MSU (Mississippi) basketball",
])
def test_blocked(text):
    assert bl.is_blocked(text)


@pytest.mark.parametrize("text", [
    "Michigan State at Ohio State", "Missouri State Bears vs Drake", "MSU Spartans vs Michigan",
    "MSU (Michigan State) basketball", "Missouri State MSU Bears", "Ole Miss vs LSU", "Mississippi Valley State",
])
def test_not_blocked(text):
    assert not bl.is_blocked(text), text


def test_bare_msu_ambiguous_is_blocked_and_logged():
    n = len(bl.review_log.items)
    assert bl.is_blocked("Will MSU win tonight?")
    assert len(bl.review_log.items) == n + 1


def test_michigan_state_with_mississippi_state_is_blocked():
    assert bl.is_blocked("Michigan State vs Mississippi State")


def test_market_fields_and_combo_legs():
    m = {"ticker": "KXCOMBO-1", "title": "3-leg parlay", "legs": [{"title": "Lakers win"}, {"yes_sub_title": "Mississippi State"}]}
    assert bl.check_market(m).blocked
    assert bl.check_market({"ticker": "X", "rules_primary": "If Mississippi State wins the SEC..."}).blocked
    assert not bl.check_market({"ticker": "KXNBAGAME-1", "title": "Lakers at Celtics"}).blocked


def test_whole_event_exclusion():
    ms = [{"ticker": "SEC-ALA", "yes_sub_title": "Alabama"}, {"ticker": "SEC-MSST", "yes_sub_title": "Mississippi State"}]
    assert bl.event_excluded(ms)
    assert bl.filter_markets(ms) == [ms[0]]


def test_block_cannot_be_disabled(monkeypatch):
    monkeypatch.setenv("KIL_DISABLE_BLOCKLIST", "1")
    assert bl.is_enabled() is True
    assert bl.is_blocked("Mississippi State")
    assert isinstance(bl.ALWAYS_BLOCKED, tuple)
