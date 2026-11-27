import json
from datetime import date
from pathlib import Path

import httpx

from kil_capital.ufc import desk as D
from kil_capital.ufc.history import FILES, diff_row, load_bouts, norm, walk
from kil_capital.ufc.model import FightModel, devig, prob_to_american

FIX = Path(__file__).parent / "fixtures" / "ufc"

SB = {"events": [{"id": "600062700", "name": "UFC Fight Night: Test", "date": "2026-12-05T15:00Z", "competitions": [
    {"id": "401936473", "date": "2026-12-05T15:00Z", "type": {"abbreviation": "Lightweight"},
     "format": {"regulation": {"periods": 3}},
     "status": {"type": {"state": "pre", "shortDetail": "12/5 - 10:00 AM EST"}},
     "competitors": [
         {"id": "4689965", "order": 1, "winner": False, "athlete": {"displayName": "Mateusz Rębecki"},
          "records": [{"type": "total", "summary": "21-5-0"}]},
         {"id": "5110006", "order": 2, "winner": False, "athlete": {"displayName": "Elves Brener"},
          "records": [{"type": "total", "summary": "17-6-0"}]}]}]}]}
ODDS = {"items": [{"provider": {"name": "DraftKings"},
                   "homeAthleteOdds": {"moneyLine": -130, "current": {"moneyLine": {"american": "-130"}},
                                       "athlete": {"$ref": "http://x/athletes/4689965?lang=en"}},
                   "awayAthleteOdds": {"moneyLine": 110, "current": {"moneyLine": {"american": "+110"}},
                                       "athlete": {"$ref": "http://x/athletes/5110006?lang=en"}}}]}


def transport(req: httpx.Request):
    u = str(req.url)
    if "scrape_ufc_stats" in u:
        return httpx.Response(200, content=(FIX / u.rsplit("/", 1)[-1]).read_bytes())
    if "scoreboard" in u:
        return httpx.Response(200, json=SB)
    if "/odds" in u:
        return httpx.Response(200, json=ODDS)
    return httpx.Response(404)


class Pub:
    def __init__(self, asks):
        self.asks = asks

    def markets(self, **kw):
        ms = [{"ticker": f"KXUFCFIGHT-26DEC05REBBRE-{n[:3].upper()}", "event_ticker": "KXUFCFIGHT-26DEC05REBBRE",
               "yes_sub_title": n, "title": f"{n} wins", "yes_bid_dollars": f"{a - 0.01:.2f}",
               "yes_ask_dollars": f"{a:.2f}"} for n, a in self.asks.items()]
        return ms, None


def run(tmp_path, asks):
    d = D.UfcDesk(Pub(asks), tmp_path, httpx.Client(transport=httpx.MockTransport(transport)), raw_dir=tmp_path / "raw")
    return d.refresh(max_trade=10, today=date(2026, 11, 27))


def test_history_rows_use_only_prior_fights():
    bouts, tott = load_bouts(FIX)
    rows, fighters = walk(bouts, tott)
    first = rows[0]
    assert first[1]["debut"] == 1.0 and first[2]["debut"] == 1.0   # nobody had fought yet
    assert fighters[norm("Mateusz Rebecki")].wins == 2
    assert fighters[norm("Joe Old")].n == 2


def test_model_is_symmetric():
    bouts, tott = load_bouts(FIX)
    rows, _ = walk(bouts, tott)
    X = [diff_row(a, b) for _, a, b in rows]
    m = FightModel(5.0).fit(X, [1.0, 1.0, 0.0])
    assert abs(m.prob([X[1]])[0] + m.prob([[-v for v in X[1]]])[0] - 1) < 1e-9


def test_lines():
    assert prob_to_american(0.5652) == -130
    assert prob_to_american(0.40) == 150
    a, b = devig(-130, 110)
    assert abs(a + b - 1) < 1e-9 and a > 0.5


def test_fair_price_no_bet(tmp_path):
    out = run(tmp_path, {"Mateusz Rebecki": 0.56, "Elves Brener": 0.46})
    f = out["fights"][0]
    assert f["a"]["vegas"] == -130 and f["b"]["vegas"] == 110
    assert f["a"]["ticker"] and f["b"]["ticker"]
    assert f["pick"]["label"] == "No bet" and "fair" in f["pick"]["reason"]
    assert f["kil_line"]["a"] is not None and f["a"]["ufc_record"] == "2-0"
    json.dumps(out)


def test_gap_makes_a_capped_bet(tmp_path):
    out = run(tmp_path, {"Mateusz Rebecki": 0.48, "Elves Brener": 0.55})
    p = out["fights"][0]["pick"]
    assert p["label"] == "BET" and p["name"] == "Mateusz Rębecki"
    assert 0 < p["stake"] <= 10 and p["edge"] >= D.MIN_GAP
    assert p["conf"] in ("High", "Medium")
    # paper record keeps the bet
    trk = json.loads((tmp_path / "ufc" / "track.json").read_text())
    assert trk["fights"]["401936473"]["bet"]["label"] == "BET"


def test_no_vegas_line_never_bets(tmp_path, monkeypatch):
    monkeypatch.setattr(D.UfcDesk, "_odds", lambda self, f: None)
    out = run(tmp_path, {"Mateusz Rebecki": 0.30, "Elves Brener": 0.30})
    assert out["fights"][0]["pick"]["label"] == "No bet"
    assert "Vegas" in out["fights"][0]["pick"]["reason"]
