"""
Tests for Hyperliquid Spot Grid Bot (tests/test_grid_bot.py)
"""

import pytest
import spot_grid_bot as SGB

BUILDER_WALLET = "0x3f294E8CFc89B9f0Df5608D601fBaCf385E6DbEc".lower()


def test_calculate_geometric_grid_levels():
    lower = 100.0
    upper = 150.0
    n_levels = 5
    levels = SGB.calculate_grid_levels(lower, upper, n_levels, mode="geometric")
    assert len(levels) == 5
    assert levels[0] == pytest.approx(100.0)
    assert levels[-1] == pytest.approx(150.0)
    ratios = [levels[i + 1] / levels[i] for i in range(len(levels) - 1)]
    for r in ratios:
        assert r == pytest.approx(ratios[0], rel=1e-4)


def test_calculate_arithmetic_grid_levels():
    lower = 100.0
    upper = 140.0
    n_levels = 5
    levels = SGB.calculate_grid_levels(lower, upper, n_levels, mode="arithmetic")
    assert levels == [100.0, 110.0, 120.0, 130.0, 140.0]


def test_calculate_grid_levels_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        SGB.calculate_grid_levels(100.0, 140.0, 1)
    with pytest.raises(ValueError):
        SGB.calculate_grid_levels(140.0, 100.0, 5)
    with pytest.raises(ValueError):
        SGB.calculate_grid_levels(100.0, 140.0, 5, mode="invalid")


def test_build_order_payload_includes_builder_fee_in_tenths_of_bps():
    order = SGB.create_grid_order(
        coin="@107",
        is_buy=True,
        sz=1.5,
        px=60.0,
        fee_bps=5,
        builder_address=BUILDER_WALLET,
    )
    assert order["coin"] == "@107"
    assert order["is_buy"] is True
    assert order["sz"] == 1.5
    assert order["limit_px"] == 60.0
    assert order["order_type"] == {"limit": {"tif": "Alo"}}
    assert "builder" in order
    assert order["builder"]["b"] == BUILDER_WALLET
    # Hyperliquid builder fee `f` is in tenths of a basis point: 5 bps = 50
    assert order["builder"]["f"] == 50


def test_bps_to_hl_builder_f_validation():
    assert SGB.bps_to_hl_builder_f(0) == 0
    assert SGB.bps_to_hl_builder_f(1) == 10
    assert SGB.bps_to_hl_builder_f(5) == 50
    with pytest.raises(ValueError):
        SGB.bps_to_hl_builder_f(-1)
    with pytest.raises(ValueError):
        SGB.bps_to_hl_builder_f(101)


def test_grid_initial_distribution():
    levels = [50.0, 60.0, 70.0, 80.0, 90.0]
    current_price = 68.0
    capital_usd = 100.0

    plan = SGB.generate_initial_grid_orders(
        coin="@107",
        levels=levels,
        current_price=current_price,
        total_capital=capital_usd,
        fee_bps=5,
        builder_address=BUILDER_WALLET,
    )

    buys = plan["buy_orders"]
    sells = plan["sell_orders"]

    assert len(buys) == 2
    assert [b["limit_px"] for b in buys] == [50.0, 60.0]
    assert all(b["is_buy"] is True for b in buys)
    assert all(b["builder"]["b"] == BUILDER_WALLET for b in buys)
    assert all(b["builder"]["f"] == 50 for b in buys)

    assert len(sells) == 3
    assert [s["limit_px"] for s in sells] == [70.0, 80.0, 90.0]
    assert all(s["is_buy"] is False for s in sells)
    assert all(s["builder"]["b"] == BUILDER_WALLET for s in sells)
    assert all(s["builder"]["f"] == 50 for s in sells)


def test_format_grid_plan_reflects_custom_fee():
    levels = [50.0, 60.0, 70.0, 80.0]
    plan = SGB.generate_initial_grid_orders(
        coin="@107",
        levels=levels,
        current_price=65.0,
        total_capital=100.0,
        fee_bps=10,
        builder_address=BUILDER_WALLET,
    )
    rendered = SGB.format_grid_plan(plan, "@107", 65.0)
    assert "10 bps (f=100)" in rendered
