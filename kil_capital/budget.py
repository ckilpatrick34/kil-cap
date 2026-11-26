"""Fit the whole slate inside a small bankroll.

Each pick's quarter-Kelly stake is computed on its own, so ten picks at $5 can ask for $50 on a $100
bankroll.  This caps the slate's total open risk (`budget`) and each bet (`max_bet`), favourites first:
win-likely picks (fair >= 55%) are filled before longer shots, best expected profit first within each.
Picks that don't fit are kept as watch-only (stake 0)."""
from __future__ import annotations

from .sports.segments import size

FAVOURITE = 0.55


def rank_key(p: dict):
    return (p["fair"] < FAVOURITE, -p.get("exp_profit", 0), -p["edge"])


def allocate(picks: list[dict], bankroll: float, budget: float, max_bet: float, min_fair: float = 0.0) -> list[dict]:
    """min_fair=FAVOURITE keeps underdogs watch-only (the dashboard's default 'win-majority' slate)."""
    left, out = max(0.0, budget), []
    for p in sorted(picks, key=rank_key):
        sz = size(p["fair"], p["price"], bankroll, min(max_bet, left), p.get("segment_mult", 1.0))
        take = sz["count"] >= 1 and p["fair"] >= min_fair
        if take:
            left -= sz["stake"]
        out.append({**p, "slate": take, "count": sz["count"] if take else 0, "stake": sz["stake"] if take else 0.0,
                    "exp_profit": sz["exp_profit"] if take else 0.0, "kelly_stake": p.get("stake", 0)})
    return out


if __name__ == "__main__":   # self-check: total never exceeds the budget, each bet never exceeds max_bet
    ps = [{"ticker": str(i), "fair": 0.6 + i * 0.01, "price": 0.5, "edge": 0.08, "exp_profit": 1} for i in range(20)]
    a = allocate(ps, 100, 25, 3)
    assert sum(p["stake"] for p in a) <= 25 and max(p["stake"] for p in a) <= 3 and any(not p["slate"] for p in a)
    print("ok", sum(p["slate"] for p in a), round(sum(p["stake"] for p in a), 2))
