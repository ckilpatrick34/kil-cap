"""Exact Decimal money, Kalshi fees and tick grid (spec v4 §10).

Fee formulas (Kalshi fee schedule v7.7.26, verified 2026-11-24 per spec):
    taker = roundup(M * 0.07   * C * P * (1-P))
    maker = roundup(M * 0.0175 * C * P * (1-P))   on maker-fee series only
fee_type:
    quadratic                        -> maker fee 0
    quadratic_with_maker_fees        -> maker = 0.25 x taker
    quadratic_with_combo_maker_fees  -> maker = 0.50 x taker
    flat                             -> unknown formula: refused (FEE_UNKNOWN) until verified

[VERIFY] Rounding.  The build historically used "ceil to $0.000001 then floor the balance
change to the cent".  The current schedule says fees are rounded up "such that fee +
positionCost is rounded to a centicent".  Default here = ceil the fee to a centicent
($0.0001).  Switch with FEE_ROUNDING if Kalshi's worked examples say otherwise, and update
tests/test_money.py golden values.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation

D = Decimal
ZERO = D("0")
ONE = D("1")
CENT = D("0.01")
CENTICENT = D("0.0001")
MICRO = D("0.000001")
TAKER_RATE = D("0.07")
MAKER_RATE = D("0.0175")

FEE_ROUNDING = "centicent"  # or "legacy_micro"

MAKER_SHARE = {
    "quadratic": ZERO,
    "quadratic_with_maker_fees": D("0.25"),
    "quadratic_with_combo_maker_fees": D("0.5"),
}


class FeeUnknown(ValueError):
    pass


def dec(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    try:
        return D(str(x))
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"not a number: {x!r}") from e


def _round_fee(raw: Decimal) -> Decimal:
    if FEE_ROUNDING == "legacy_micro":
        return raw.quantize(MICRO, rounding=ROUND_CEILING)
    return raw.quantize(CENTICENT, rounding=ROUND_CEILING)


def fee(price, count, *, fee_type: str, multiplier, liquidity: str) -> Decimal:
    """Fee in dollars for one fill.  price is in dollars (0..1)."""
    p, c, m = dec(price), dec(count), dec(multiplier)
    if not (ZERO < p < ONE):
        raise ValueError("price must be strictly between 0 and 1")
    if fee_type not in MAKER_SHARE:
        raise FeeUnknown(f"fee_type {fee_type!r} not supported")
    base = m * c * p * (ONE - p)
    if liquidity == "taker":
        raw = TAKER_RATE * base
    elif liquidity == "maker":
        raw = TAKER_RATE * MAKER_SHARE[fee_type] * base
    else:
        raise ValueError("liquidity must be maker or taker")
    return _round_fee(raw)


def balance_change_floor(x: Decimal) -> Decimal:
    """Legacy: floor a balance change to the cent."""
    return x.quantize(CENT, rounding=ROUND_FLOOR)


# ---- tick grid ---------------------------------------------------------------------

@dataclass(frozen=True)
class PriceRange:
    start: Decimal
    end: Decimal
    step: Decimal


DEFAULT_RANGES = (PriceRange(D("0.01"), D("0.99"), D("0.01")),)


def parse_price_ranges(raw) -> tuple[PriceRange, ...]:
    """Parse Kalshi `price_ranges` ([{start, end, step}] as dollar strings). Never assume them."""
    if not raw:
        return DEFAULT_RANGES
    out = []
    for r in raw:
        out.append(PriceRange(dec(r["start"]), dec(r["end"]), dec(r["step"])))
    return tuple(out)


def on_tick(price, ranges=DEFAULT_RANGES) -> bool:
    p = dec(price)
    for r in ranges:
        if r.start <= p <= r.end:
            return ((p - r.start) % r.step) == 0
    return False


def snap(price, ranges=DEFAULT_RANGES, direction: str = "nearest") -> Decimal:
    """Snap a price to the tick grid (used by the backtester)."""
    p = dec(price)
    best = None
    for r in ranges:
        lo, hi = r.start, r.end
        q = min(max(p, lo), hi)
        n = (q - lo) / r.step
        if direction == "down":
            n = n.to_integral_value(rounding=ROUND_FLOOR)
        elif direction == "up":
            n = n.to_integral_value(rounding=ROUND_CEILING)
        else:
            n = n.to_integral_value()
        cand = min(max(lo + n * r.step, lo), hi)
        if best is None or abs(cand - p) < abs(best - p):
            best = cand
    return best


# ---- order economics ---------------------------------------------------------------

def cost_basis(side: str, action: str, price, count) -> tuple[str, Decimal]:
    """Normalise an order to (effective_side_bought, price_paid_per_contract).

    On Kalshi, selling YES you don't hold is economically buying NO at 1-price and
    vice versa.  Risk math always uses the *bought* side and its price.
    """
    p = dec(price)
    if action == "buy":
        return side, p
    other = "no" if side == "yes" else "yes"
    return other, ONE - p


def max_loss(side: str, action: str, price, count, fee_amt=ZERO) -> Decimal:
    """Worst-case loss of an opening order: everything paid plus the fee."""
    _, paid = cost_basis(side, action, price, count)
    return paid * dec(count) + dec(fee_amt)


def kelly_fraction(q, price, fee_per_contract=ZERO) -> Decimal:
    """f* = (q - p_eff)/(1 - p_eff), p_eff = price + fee.  Clipped at 0."""
    q, p_eff = dec(q), dec(price) + dec(fee_per_contract)
    if p_eff >= ONE:
        return ZERO
    f = (q - p_eff) / (ONE - p_eff)
    return max(f, ZERO)
