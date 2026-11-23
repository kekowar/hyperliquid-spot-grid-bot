"""
Tests for Hyperliquid Spot Grid Bot (tests/test_grid_bot.py)
"""

import json
import pytest
import spot_grid_bot as SGB

BUILDER_WALLET = "0x3f294E8CFc89B9f0Df5608D601fBaCf385E6DbEc".lower()


def test_calculate_geometric_grid_levels():
    levels = SGB.calculate_grid_levels(100.0, 150.0, 5, mode="geometric")
    assert len(levels) == 5
    assert levels[0] == pytest.approx(100.0)
    assert levels[-1] == pytest.approx(150.0)
    ratios = [levels[i + 1] / levels[i] for i in range(len(levels) - 1)]
    for r in ratios:
        assert r == pytest.approx(ratios[0], rel=1e-4)


def test_calculate_arithmetic_grid_levels():
    levels = SGB.calculate_grid_levels(100.0, 140.0, 5, mode="arithmetic")
    assert levels == [100.0, 110.0, 120.0, 130.0, 140.0]


def test_calculate_grid_levels_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        SGB.calculate_grid_levels(100.0, 140.0, 1)
    with pytest.raises(ValueError):
        SGB.calculate_grid_levels(140.0, 100.0, 5)
    with pytest.raises(ValueError):
        SGB.calculate_grid_levels(100.0, 140.0, 5, mode="invalid")


def test_spot_price_and_size_rounding():
    # HYPE (@107) has szDecimals=2 -> max 6 decimals, 5 sig figs
    assert SGB.round_spot_price(25.123456, sz_decimals=2) == 25.123
    assert SGB.round_spot_price(61234.56, sz_decimals=5) == 61235.0
    assert SGB.round_size(1.2399, sz_decimals=2) == 1.23
    assert SGB.round_size(0.001239, sz_decimals=5) == 0.00123


def test_builder_fee_conversions():
    assert SGB.bps_to_hl_builder_f(0) == 0
    assert SGB.bps_to_hl_builder_f(1) == 10
    assert SGB.bps_to_hl_builder_f(5) == 50
    assert SGB.bps_to_max_fee_rate_str(5) == "0.05%"
    assert SGB.bps_to_max_fee_rate_str(10) == "0.1%"
    assert SGB.bps_to_max_fee_rate_str(100) == "1%"
    with pytest.raises(ValueError):
        SGB.bps_to_hl_builder_f(-1)
    with pytest.raises(ValueError):
        SGB.bps_to_hl_builder_f(101)


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
    assert order["builder"] == {"b": BUILDER_WALLET, "f": 50}


def test_grid_initial_distribution_and_min_notional_warning():
    levels = [50.0, 60.0, 70.0, 80.0, 90.0]
    plan = SGB.generate_initial_grid_orders(
        coin="@107",
        levels=levels,
        current_price=68.0,
        total_capital=100.0,
        fee_bps=5,
        builder_address=BUILDER_WALLET,
        sz_decimals=2,
    )
    assert len(plan["buy_orders"]) == 2
    assert len(plan["sell_orders"]) == 3
    assert plan["below_min_notional"] is False
    assert all(o["builder"]["f"] == 50 for o in plan["buy_orders"] + plan["sell_orders"])

    small_plan = SGB.generate_initial_grid_orders(
        coin="@107",
        levels=levels,
        current_price=68.0,
        total_capital=25.0,
        fee_bps=5,
        builder_address=BUILDER_WALLET,
    )
    assert small_plan["below_min_notional"] is True
    assert "[WARNING]" in SGB.format_grid_plan(small_plan, "@107", 68.0)


def test_compute_counter_order_on_fill():
    levels = [50.0, 60.0, 70.0, 80.0]

    # Buy filled at 60 -> place SELL at 70
    sell_counter = SGB.compute_counter_order_on_fill(
        coin="@107",
        levels=levels,
        fill_is_buy=True,
        fill_price=60.0,
        fill_sz=0.5,
        sz_decimals=2,
        fee_bps=5,
        builder_address=BUILDER_WALLET,
    )
    assert sell_counter is not None
    assert sell_counter["is_buy"] is False
    assert sell_counter["limit_px"] == 70.0
    assert sell_counter["sz"] == 0.5
    assert sell_counter["builder"]["f"] == 50

    # Sell filled at 70 -> place BUY at 60
    buy_counter = SGB.compute_counter_order_on_fill(
        coin="@107",
        levels=levels,
        fill_is_buy=False,
        fill_price=70.0,
        fill_sz=0.5,
        sz_decimals=2,
        fee_bps=5,
        builder_address=BUILDER_WALLET,
    )
    assert buy_counter is not None
    assert buy_counter["is_buy"] is True
    assert buy_counter["limit_px"] == 60.0

    # Boundary: Buy filled at top level (80) -> no upper level
    assert (
        SGB.compute_counter_order_on_fill(
            coin="@107", levels=levels, fill_is_buy=True, fill_price=80.0, fill_sz=0.5
        )
        is None
    )
    # Boundary: Sell filled at bottom level (50) -> no lower level
    assert (
        SGB.compute_counter_order_on_fill(
            coin="@107", levels=levels, fill_is_buy=False, fill_price=50.0, fill_sz=0.5
        )
        is None
    )


class _FakeInfo:
    def __init__(self, fills=None, open_orders=None):
        self.fills = fills or []
        self._open_orders = open_orders or []

    def user_fills(self, _user):
        return list(self.fills)

    def open_orders(self, _user):
        return list(self._open_orders)


class _FakeExchange:
    def __init__(self):
        self.bulk_calls = []
        self.order_calls = []
        self.cancel_calls = []

    def bulk_orders(self, order_requests, builder=None):
        self.bulk_calls.append({"orders": order_requests, "builder": builder})
        return {"status": "ok", "count": len(order_requests)}

    def order(self, name, is_buy, sz, limit_px, order_type, reduce_only=False, builder=None):
        self.order_calls.append(
            {
                "name": name,
                "is_buy": is_buy,
                "sz": sz,
                "limit_px": limit_px,
                "order_type": order_type,
                "reduce_only": reduce_only,
                "builder": builder,
            }
        )
        return {"status": "ok"}

    def cancel(self, coin, oid):
        self.cancel_calls.append((coin, oid))
        return {"status": "ok"}


def test_grid_bot_runner_deploy_rebalance_dedupe_and_cancel(tmp_path):
    state_path = tmp_path / "state.json"
    info = _FakeInfo(
        fills=[{"coin": "@107", "tid": 1, "side": "B", "px": "60.0", "sz": "0.5", "time": 1000}],
        open_orders=[
            {"coin": "@107", "oid": 101},
            {"coin": "@142", "oid": 202},
        ],
    )
    ex = _FakeExchange()

    runner = SGB.GridBotRunner(
        info=info,
        exchange=ex,
        account_address="0x1111111111111111111111111111111111111111",
        coin="@107",
        levels=[50.0, 60.0, 70.0, 80.0],
        capital=100.0,
        sz_decimals=2,
        fee_bps=5,
        builder_address=BUILDER_WALLET,
        state_file=str(state_path),
    )

    # 1. Deploy initial grid (seeds pre-existing tid=1 so it won't re-trigger)
    deployed = runner.deploy_initial_grid(current_price=65.0)
    assert deployed["exchange_response"]["status"] == "ok"
    assert len(ex.bulk_calls) == 1
    assert ex.bulk_calls[0]["builder"] == {"b": BUILDER_WALLET, "f": 50}
    assert len(ex.bulk_calls[0]["orders"]) == 4

    # 2. Pre-existing fill tid=1 is ignored
    assert runner.sync_fills_once() == []

    # 3. New BUY fill tid=2 at 60.0 triggers SELL counter-order at 70.0
    info.fills.append({"coin": "@107", "tid": 2, "side": "B", "px": "60.0", "sz": "0.5", "time": 2000})
    placed = runner.sync_fills_once()
    assert len(placed) == 1
    assert len(ex.order_calls) == 1
    assert ex.order_calls[0]["is_buy"] is False
    assert ex.order_calls[0]["limit_px"] == 70.0
    assert ex.order_calls[0]["builder"] == {"b": BUILDER_WALLET, "f": 50}

    # 4. Calling sync again does NOT duplicate tid=2
    assert runner.sync_fills_once() == []

    # 5. State persisted to JSON
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert 2 in saved["processed_tids"]

    # 6. Cancel only cancels @107 orders
    assert runner.cancel_all_coin_orders() == 1
    assert ex.cancel_calls == [("@107", 101)]
