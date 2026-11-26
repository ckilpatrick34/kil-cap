"""In-game model: the chance each Kalshi game market pays, given the score, the clock and our pre-game view.

Scoring still to come is treated as normal, with the pre-game expected margin and total and their spread
scaled by the share of the game left (the Brownian-motion model, the standard in-game win-probability
baseline).  It knows the score and the clock, not possession, field position or fouls, so the fair price
leans partly on the Kalshi mid.  Recommend-only: nothing here places an order."""
from __future__ import annotations

from .model import p_cover, p_over

# (regulation periods, seconds per period); overtime is scored on its own clock
REG = {"nfl": (4, 900), "cfb": (4, 900), "nba": (4, 720), "cbb": (2, 1200), "nhl": (3, 1200)}
W_MODEL = 0.5          # snip: fixed half-weight on our model vs the Kalshi mid; learn it once live picks have graded
CUSHION = 0.02         # max price keeps this much edge after the fee
LIVE_KINDS = ("winner", "spread", "total")


def fee(p: float) -> float:
    return 0.07 * p * (1 - p)


def frac_left(key: str, period, clock) -> float | None:
    """Share of regulation still to play; overtime counts as a small sliver, never zero."""
    if key not in REG or period is None or clock is None:
        return None
    n, plen = REG[key]
    if period > n:                                   # overtime (college football OT has no clock)
        return max(clock / (n * plen), 0.02)
    return max(((n - period) * plen + clock) / (n * plen), 0.005)


def p_yes(lg, c: dict, f: float, lead: float, pts: float, margin: float, total: float) -> float | None:
    """P(YES pays) for one contract. lead/pts are home-minus-away and points so far."""
    s = f ** 0.5
    m_end, t_end = lead + margin * f, pts + total * f
    if c["kind"] == "winner":
        p = p_cover(m_end, 0.0, lg.sigma_margin * s)
        return p if c["team"] == "home" else 1 - p
    if c["kind"] == "spread":
        return p_cover(m_end if c["team"] == "home" else -m_end, c["line"], lg.sigma_margin * s)
    if c["kind"] == "total":
        return p_over(t_end, c["line"], lg.sigma_total * s)
    return None


def max_price(fair: float) -> float | None:
    """Most you can pay (whole cents) and still keep CUSHION of edge after the fee."""
    for cents in range(99, 0, -1):
        x = cents / 100
        if fair - x - fee(x) >= CUSHION:
            return x
    return None


def level(edge: float, price: float, width: float | None, f: float) -> str:
    if f < 0.05 or not 0.10 <= price <= 0.90:        # last minutes and lopsided prices: possession decides
        return "low"
    if edge >= 0.05 and width is not None and width <= 0.04:
        return "high"
    if edge >= 0.03:
        return "medium"
    return "lean" if edge > 0 else "low"


def price_game(lg, key: str, g: dict, margin: float, total: float, rows: list[dict], label) -> dict | None:
    """Live view of one in-progress game: win chance now, and the best side of each live Kalshi market."""
    f = frac_left(key, g.get("period"), g.get("clock"))
    hs, as_ = g["home"].get("score"), g["away"].get("score")
    if f is None or hs is None or as_ is None:
        return None
    lead, pts = hs - as_, hs + as_
    out = []
    for c in rows:
        if c["kind"] not in LIVE_KINDS:
            continue
        q = p_yes(lg, c, f, lead, pts, margin, total)
        bid, ask = c.get("yes_bid"), c.get("yes_ask")
        if q is None or not bid or not ask:
            continue
        mid = (bid + ask) / 2
        fy = W_MODEL * q + (1 - W_MODEL) * mid
        sides = [("yes", ask, fy, q), ("no", round(1 - bid, 2), 1 - fy, 1 - q)]
        side, price, fair, model_p = max(sides, key=lambda s: s[2] - s[1] - fee(s[1]))
        edge = fair - price - fee(price)
        out.append({"ticker": c["ticker"], "kind": c["kind"], "team": c.get("team"), "line": c.get("line"),
                    "label": label(g, c), "side": side, "price": price, "fair": round(fair, 4),
                    "model_p": round(model_p, 4), "edge": round(edge, 4), "yes_bid": bid, "yes_ask": ask,
                    "max_price": max_price(fair), "level": level(edge, price, ask - bid, f),
                    "close_ts": c.get("close_ts")})
    out.sort(key=lambda r: -r["edge"])
    p_home = p_cover(lead + margin * f, 0.0, lg.sigma_margin * f ** 0.5)
    p_pre = p_cover(margin, 0.0, lg.sigma_margin)
    return {"frac_left": round(f, 4), "lead": lead, "p_home": round(p_home, 4), "p_home_pre": round(p_pre, 4), "rows": out}


if __name__ == "__main__":   # self-check: python -m kil_capital.sports.live
    from .leagues import LEAGUES
    nfl = LEAGUES["nfl"]
    assert frac_left("nfl", 1, 900) == 1.0 and frac_left("nfl", 2, 0) == 0.5 and frac_left("nfl", 5, 0) == 0.02
    lab = lambda g, c: c["kind"]
    g = {"period": 4, "clock": 120, "home": {"score": 24}, "away": {"score": 10}}
    v = price_game(nfl, "nfl", g, 3.0, 45.0, [{"ticker": "T", "kind": "winner", "team": "home",
                                               "yes_bid": 0.80, "yes_ask": 0.82}], lab)
    assert v["p_home"] > 0.99 and v["rows"][0]["side"] == "yes" and v["rows"][0]["level"] == "low", v
    g = {"period": 2, "clock": 0, "home": {"score": 14}, "away": {"score": 14}}
    v = price_game(nfl, "nfl", g, 0.0, 45.0, [{"ticker": "T", "kind": "winner", "team": "home",
                                               "yes_bid": 0.30, "yes_ask": 0.32}], lab)
    assert abs(v["p_home"] - 0.5) < 1e-9 and v["rows"][0]["side"] == "yes" and v["rows"][0]["level"] == "high", v
    assert max_price(0.5) is not None and max_price(0.01) is None
    print("live.py self-check ok")
