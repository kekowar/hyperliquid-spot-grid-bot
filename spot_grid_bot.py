"""
Hyperliquid Spot Grid Bot (Non-Custodial)
-----------------------------------------
Open-source spot grid planner and order-payload builder for Hyperliquid Spot markets.
Constructs passive maker limit orders (Post-Only / Alo) across a geometric or arithmetic grid
with Hyperliquid's native HIP-1 Builder Fee attached.

Note on Builder Fee units (Hyperliquid protocol):
  In Hyperliquid's `builder` payload `{"b": address, "f": fee}`, `f` is denominated in
  tenths of a basis point (10 = 1 bps = 0.01%). Therefore 5 bps (0.05%) = 50.

Repository: https://github.com/kekowar/hyperliquid-spot-grid-bot
"""

import argparse
import json
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_BUILDER_WALLET = "0x3f294E8CFc89B9f0Df5608D601fBaCf385E6DbEc".lower()
DEFAULT_FEE_BPS = 5  # 5 bps = 0.05% (50 tenths of a basis point on Hyperliquid)
HL_INFO_URL = "https://api.hyperliquid.xyz/info"


def bps_to_hl_builder_f(fee_bps: int) -> int:
    """Convert basis points (bps) to Hyperliquid builder fee units (tenths of a bps)."""
    if fee_bps < 0 or fee_bps > 100:
        raise ValueError("Spot builder fee_bps must be between 0 and 100 (0% - 1.00%)")
    return int(fee_bps) * 10


def fetch_spot_mid_price(coin: str, timeout: int = 8) -> float:
    """Fetch current spot mid price from Hyperliquid public /info endpoint."""
    payload = json.dumps({"type": "l2Book", "coin": coin}).encode("utf-8")
    req = urllib.request.Request(
        HL_INFO_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    levels = data.get("levels", [[], []])
    if not levels or not levels[0] or not levels[1]:
        raise ValueError(f"Empty order book returned for {coin}")
    bid = float(levels[0][0]["px"])
    ask = float(levels[1][0]["px"])
    return (bid + ask) / 2.0


def calculate_grid_levels(
    lower: float,
    upper: float,
    n_levels: int,
    mode: str = "geometric",
) -> List[float]:
    """Calculate price points for the grid."""
    if n_levels < 2:
        raise ValueError("n_levels must be >= 2")
    if lower <= 0 or upper <= lower:
        raise ValueError("Invalid lower/upper bounds")

    if mode == "geometric":
        ratio = (upper / lower) ** (1.0 / (n_levels - 1))
        return [round(lower * (ratio ** i), 6) for i in range(n_levels)]
    elif mode == "arithmetic":
        step = (upper - lower) / (n_levels - 1)
        return [round(lower + i * step, 6) for i in range(n_levels)]
    else:
        raise ValueError(f"Unknown grid mode: {mode}")


def create_grid_order(
    coin: str,
    is_buy: bool,
    sz: float,
    px: float,
    fee_bps: int = DEFAULT_FEE_BPS,
    builder_address: str = DEFAULT_BUILDER_WALLET,
) -> Dict[str, Any]:
    """Format an order payload with Post-Only TIF (Alo) and Hyperliquid builder fee."""
    return {
        "coin": coin,
        "is_buy": is_buy,
        "sz": sz,
        "limit_px": px,
        "order_type": {"limit": {"tif": "Alo"}},  # Post-Only (Maker)
        "reduce_only": False,
        "builder": {
            "b": builder_address.lower(),
            "f": bps_to_hl_builder_f(fee_bps),
        },
    }


def generate_initial_grid_orders(
    coin: str,
    levels: List[float],
    current_price: float,
    total_capital: float,
    fee_bps: int = DEFAULT_FEE_BPS,
    builder_address: str = DEFAULT_BUILDER_WALLET,
) -> Dict[str, Any]:
    """Generate initial buy and sell orders partitioned by current market price."""
    buy_levels = [p for p in levels if p < current_price]
    sell_levels = [p for p in levels if p > current_price]

    total_orders = len(buy_levels) + len(sell_levels)
    if total_orders == 0:
        return {
            "buy_orders": [],
            "sell_orders": [],
            "usd_per_order": 0.0,
            "total_capital": total_capital,
            "fee_bps": fee_bps,
            "builder_address": builder_address.lower(),
        }

    usd_per_order = total_capital / total_orders

    buy_orders = []
    for px in buy_levels:
        sz = round(usd_per_order / px, 4)
        buy_orders.append(
            create_grid_order(
                coin,
                is_buy=True,
                sz=sz,
                px=px,
                fee_bps=fee_bps,
                builder_address=builder_address,
            )
        )

    sell_orders = []
    for px in sell_levels:
        sz = round(usd_per_order / px, 4)
        sell_orders.append(
            create_grid_order(
                coin,
                is_buy=False,
                sz=sz,
                px=px,
                fee_bps=fee_bps,
                builder_address=builder_address,
            )
        )

    return {
        "buy_orders": buy_orders,
        "sell_orders": sell_orders,
        "usd_per_order": usd_per_order,
        "total_capital": total_capital,
        "fee_bps": fee_bps,
        "builder_address": builder_address.lower(),
    }


def format_grid_plan(plan: Dict[str, Any], coin: str, current_price: float) -> str:
    """Format readable summary table of the grid plan."""
    fee_bps = plan.get("fee_bps", DEFAULT_FEE_BPS)
    builder = plan.get("builder_address", DEFAULT_BUILDER_WALLET)
    fee_f = bps_to_hl_builder_f(fee_bps)
    lines = [
        "==================================================================",
        f"  HYPERLIQUID SPOT GRID BOT: {coin}",
        "==================================================================",
        f"Current Market Price:   {current_price:,.4f}",
        f"Capital Allocated:      ${plan['total_capital']:,.2f} USD (${plan['usd_per_order']:,.2f} per order)",
        f"Builder Fee Attached:   {fee_bps} bps (f={fee_f}) -> {builder}",
        "",
        "BUY ORDERS (placed below current price):",
    ]
    for b in reversed(plan["buy_orders"]):
        lines.append(f"  [BUY]  {b['sz']:>8.4f} @ {b['limit_px']:>10.4f}  (~${b['sz']*b['limit_px']:>6.2f})")
    lines.append(f"--- CURRENT PRICE: {current_price:,.4f} ---")
    lines.append("SELL ORDERS (placed above current price):")
    for s in plan["sell_orders"]:
        lines.append(f"  [SELL] {s['sz']:>8.4f} @ {s['limit_px']:>10.4f}  (~${s['sz']*s['limit_px']:>6.2f})")
    lines.append("==================================================================")
    return "\n".join(lines)


def resolve_reference_price(
    coin: str,
    lower: float,
    upper: float,
    explicit_price: Optional[float] = None,
    use_live_price: bool = False,
) -> float:
    """Resolve reference market price from explicit input, live L2 book, or range midpoint."""
    if explicit_price is not None:
        if explicit_price <= 0:
            raise ValueError("Reference price must be > 0")
        return explicit_price
    if use_live_price:
        return fetch_spot_mid_price(coin)
    return (lower + upper) / 2.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Hyperliquid Spot Grid Trading Bot (Non-Custodial)")
    parser.add_argument("--coin", type=str, default="@107", help="Spot market symbol (e.g. @107 for HYPE, @142 for UBTC, PURR/USDC)")
    parser.add_argument("--lower", type=float, default=50.0, help="Lower price boundary (USD)")
    parser.add_argument("--upper", type=float, default=80.0, help="Upper price boundary (USD)")
    parser.add_argument("--grids", type=int, default=10, help="Number of grid levels")
    parser.add_argument("--mode", type=str, default="geometric", choices=["geometric", "arithmetic"], help="Grid distribution mode")
    parser.add_argument("--capital", type=float, default=100.0, help="Total USD capital to deploy in grid")
    parser.add_argument("--price", type=float, default=None, help="Override reference market price (defaults to midpoint of lower/upper)")
    parser.add_argument("--live-price", action="store_true", help="Fetch live spot mid price from Hyperliquid public API")
    parser.add_argument("--fee-bps", type=int, default=DEFAULT_FEE_BPS, help="Builder fee in bps (default 5 = 0.05%%)")
    parser.add_argument("--plan", action="store_true", help="Print grid plan and exit (dry-run mode)")
    args = parser.parse_args()

    levels = calculate_grid_levels(args.lower, args.upper, args.grids, mode=args.mode)
    current_price = resolve_reference_price(
        coin=args.coin,
        lower=args.lower,
        upper=args.upper,
        explicit_price=args.price,
        use_live_price=args.live_price,
    )
    plan = generate_initial_grid_orders(
        coin=args.coin,
        levels=levels,
        current_price=current_price,
        total_capital=args.capital,
        fee_bps=args.fee_bps,
        builder_address=DEFAULT_BUILDER_WALLET,
    )

    print(format_grid_plan(plan, args.coin, current_price))


if __name__ == "__main__":
    main()
