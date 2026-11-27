from kil_capital.book import Book, candidates


def game(gid="1", start="2099-11-29T18:00:00Z", wind=None, lk="nfl", total=44.5, contracts=None, margin=3.0, p_home=0.6):
    return {"id": gid, "league": "NFL", "league_key": lk, "name": "AAA @ HHH", "start": start, "state": "pre",
            "home": {"abbr": "HHH"}, "away": {"abbr": "AAA"},
            "book": {"total": total, "margin": margin, "p_home": p_home},
            "model": {"weather": {"wind_mph": wind} if wind is not None else None},
            "contracts": contracts if contracts is not None else [
                {"ticker": f"T{gid}", "kind": "total", "line": 44.5, "yes_bid": 0.50, "yes_ask": 0.52,
                 "p_book": 0.5, "close_ts": None}]}


def test_wind_under_beats_other_sleeves_and_respects_cap():
    c = candidates([game(wind=18)])
    assert len(c) == 1 and c[0]["sleeve"] == "wind" and c[0]["side"] == "no" and c[0]["price"] == 0.5
    assert c[0]["title"].endswith("Under 44.5")
    pricey = game(wind=18, contracts=[{"ticker": "X", "kind": "total", "line": 44.5, "yes_bid": 0.40,
                                       "yes_ask": 0.42, "p_book": 0.41}])
    assert candidates([pricey]) == []          # under costs 60c, above the 54c cap; no 3c gap either


def test_primetime_is_sunday_or_monday_night_eastern():
    sun_night = "2099-11-30T01:20:00Z"          # Sun 8:20pm ET
    assert candidates([game(start=sun_night)])[0]["sleeve"] == "prime"
    assert candidates([game(start="2099-11-29T18:00:00Z")]) == []   # Sun 1pm ET, no gap either


def test_gap_needs_three_cents_after_fee_and_skips_stale_huge_gaps():
    wc = lambda ask: [{"ticker": "W", "kind": "winner", "team": "home", "yes_bid": ask - 0.02, "yes_ask": ask,
                       "p_book": 0.60}]
    assert candidates([game(contracts=wc(0.55))])[0]["sleeve"] == "gap"     # 60 - 55 - 1.7 fee = 3.3c
    assert candidates([game(contracts=wc(0.57))]) == []                     # 1.3c after fee
    assert candidates([game(contracts=wc(0.40))]) == []                     # 18c: stale odds, not an edge


def test_book_one_bet_per_game_caps_and_grades(tmp_path):
    b = Book(tmp_path / "b.json", 100, 100, 10)
    cands = candidates([game(wind=20), game("2", wind=20)])
    assert b.enter(cands, "v") == 2 and b.enter(cands, "v") == 0
    bet = b.d["bets"]["T1"]
    assert bet["cost"] <= 5 and bet["count"] == 9                         # NFL capped at $5: 50c + fee
    class Pub:
        def market(self, t): return {"result": "no"}
    b.grade(Pub(), now=4102444800 + 10**6)
    s = b.summary()
    assert s["total"]["w"] == 2 and s["by"]["sleeve"][0]["key"] == "wind" and s["total"]["pnl"] > 0


def test_book_never_risks_more_than_cash(tmp_path):
    b = Book(tmp_path / "b.json", 15, 15, 10)
    assert b.enter(candidates([game(str(i), wind=20) for i in range(5)]), "v") == 3     # $4.66 each, $15 cash


def test_gap_ignores_spreads_and_totals_whose_book_price_is_a_guess():
    tot = [{"ticker": "O", "kind": "total", "line": 44.5, "yes_bid": 0.40, "yes_ask": 0.45, "p_book": 0.60}]
    spr = [{"ticker": "S", "kind": "spread", "team": "home", "line": 3.5, "yes_bid": 0.40, "yes_ask": 0.45, "p_book": 0.60}]
    assert candidates([game(contracts=tot)]) == [] and candidates([game(contracts=spr)]) == []
    ml = [{"ticker": "W", "kind": "winner", "team": "home", "yes_bid": 0.53, "yes_ask": 0.55, "p_book": 0.60}]
    g = game(contracts=ml); del g["book"]["p_home"]
    assert candidates([g]) == []                                            # no moneyline odds: no gap


def test_gap_sleeve_open_risk_is_capped(tmp_path):
    b = Book(tmp_path / "b.json", 100, 100, 10)
    ml = lambda i: [{"ticker": f"W{i}", "kind": "winner", "team": "home", "yes_bid": 0.53, "yes_ask": 0.55, "p_book": 0.60}]
    n = b.enter(candidates([game(str(i), contracts=ml(i)) for i in range(10)]), "v")
    assert n == 5 and b._open_cost("gap") <= 25                              # ~$4.98 each, $25 cap


def test_nfl_capped_at_five_even_when_gap_graduates(tmp_path):
    ml = [{"ticker": "W", "kind": "winner", "team": "home", "yes_bid": 0.53, "yes_ask": 0.55, "p_book": 0.60}]
    costs = {}
    for lg in ("NFL", "NBA"):
        b = Book(tmp_path / f"{lg}.json", 100, 100, 10)
        b.gap_proven = lambda: True                                         # $10 stake once proven
        g = game(contracts=ml); g["league"] = lg
        assert b.enter(candidates([g]), "v") == 1
        costs[lg] = b.d["bets"]["W"]["cost"]
    assert costs["NFL"] <= 5 < costs["NBA"] <= 10
