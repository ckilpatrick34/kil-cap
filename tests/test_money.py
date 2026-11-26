from decimal import Decimal as D

import pytest

from kil_capital.core import money


def test_taker_fee_50c_m1():
    # 0.07 * 1 * 0.5 * 0.5 = 0.0175 -> 1.75c per contract (spec §10)
    assert money.fee("0.50", 1, fee_type="quadratic", multiplier=1, liquidity="taker") == D("0.0175")
    assert money.fee("0.50", 100, fee_type="quadratic", multiplier=1, liquidity="taker") == D("1.75")


def test_maker_fees_by_type():
    assert money.fee("0.50", 1, fee_type="quadratic", multiplier=1, liquidity="maker") == 0
    # 0.25 x taker = 0.004375 -> ceil to centicent 0.0044 (~0.44c)
    assert money.fee("0.50", 1, fee_type="quadratic_with_maker_fees", multiplier=1, liquidity="maker") == D("0.0044")
    # combos: 50% of taker = 0.875c
    assert money.fee("0.50", 1, fee_type="quadratic_with_combo_maker_fees", multiplier=1, liquidity="maker") == D("0.0088")
    assert money.fee("0.50", 100, fee_type="quadratic_with_combo_maker_fees", multiplier=1, liquidity="maker") == D("0.875")


def test_mlb_half_multiplier_and_fee_free():
    # KXMLBGAME M=0.5: taker 0.875c at 50c
    assert money.fee("0.50", 100, fee_type="quadratic_with_maker_fees", multiplier="0.5", liquidity="taker") == D("0.875")
    # KXBTCY / KXETHY M=0: fee-free
    assert money.fee("0.30", 10, fee_type="quadratic", multiplier=0, liquidity="taker") == 0


def test_flat_fee_refused_until_verified():
    with pytest.raises(money.FeeUnknown):
        money.fee("0.5", 1, fee_type="flat", multiplier=1, liquidity="taker")


def test_tick_grid():
    ranges = money.parse_price_ranges([{"start": "0.0000", "end": "0.1000", "step": "0.0010"},
                                       {"start": "0.1000", "end": "0.9000", "step": "0.0100"},
                                       {"start": "0.9000", "end": "1.0000", "step": "0.0010"}])
    assert money.on_tick("0.055", ranges)
    assert not money.on_tick("0.555", ranges)
    assert money.on_tick("0.95", ranges) and money.on_tick("0.951", ranges)
    assert money.snap("0.555", ranges, "down") == D("0.55")


def test_max_loss_and_sell_normalisation():
    assert money.max_loss("yes", "buy", "0.30", 10) == D("3.00")
    # selling YES you don't hold = buying NO at 0.70
    assert money.max_loss("yes", "sell", "0.30", 10) == D("7.00")


def test_kelly():
    f = money.kelly_fraction("0.60", "0.50", "0")
    assert f == D("0.2")
    assert money.kelly_fraction("0.40", "0.50") == 0
