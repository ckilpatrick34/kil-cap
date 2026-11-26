from kil_capital.research.lines import ats, ou, grade


def g(hs, as_, spread=None, total=None, **k):
    return {"hs": hs, "as_": as_, "spread": spread, "total": total, **k}


def test_ats_and_push():
    assert ats(g(24, 20, spread=3), 1) == 1      # home -3 wins by 4
    assert ats(g(24, 20, spread=3), -1) == 0
    assert ats(g(23, 20, spread=3), 1) is None    # push


def test_ou_uses_open_line_when_asked():
    r = g(110, 100, total=215, total_open=205)
    assert ou(r, 1) == 0 and ou(r, 1, "total_open") == 1


def test_grade_breakeven_roi_zero():
    r = grade([1] * 110 + [0] * 100)
    assert abs(r["roi"]) < 1e-9
