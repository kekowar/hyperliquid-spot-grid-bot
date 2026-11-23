"""
Hyperliquid Spot Grid Bot (Non-Custodial) — v0.3
------------------------------------------------
Open-source, non-custodial Spot Grid Trading Bot for Hyperliquid Spot markets
(e.g. HYPE/USDC, UBTC/USDC, UETH/USDC, PURR/USDC).

Features:
- Friendly spot pair resolution (`HYPE`, `HYPE/USDC`, or `@107` -> canonical Hyperliquid pair).
- Dry-run planner (`--plan`) with optional live mid-price & `szDecimals` lookup (`--live-price`).
- Hyperliquid Spot precision rounding (`szDecimals`, 5 significant figures, max `8 - szDecimals` decimals).
- Balance-aware live deployment: if starting with 100% USDC, places BUY grid below market and
  automatically places upper SELL orders as buys fill.
- One-time EIP-712 Builder Fee approval (`--approve-builder`) signed by the user's Main Wallet.
- Builder eligibility diagnostics (`--check-builder`).
- Live non-custodial execution and automatic fill-rebalancing loop (`--run`) using an API/Agent wallet
  that has NO withdrawal permissions.
- Native Hyperliquid HIP-1 Builder Fee (`f` in tenths of a basis point: 5 bps = 50).

Repository: https://github.com/kekowar/hyperliquid-spot-grid-bot
"""

import argparse
import json
import math
import os
import signal
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_BUILDER_WALLET = "0x3f294E8CFc89B9f0Df5608D601fBaCf385E6DbEc".lower()
DEFAULT_FEE_BPS = 5  # 5 bps = 0.05% (50 tenths of a basis point on Hyperliquid)
MIN_ORDER_NOTIONAL_USD = 10.0  # Hyperliquid minimum spot order value
HL_MAINNET_API = "https://api.hyperliquid.xyz"
HL_TESTNET_API = "https://api.hyperliquid-testnet.xyz"


def bps_to_hl_builder_f(fee_bps: int) -> int:
    """Convert basis points (bps) to Hyperliquid builder fee units (tenths of a bps)."""
    if fee_bps < 0 or fee_bps > 100:
        raise ValueError("Spot builder fee_bps must be between 0 and 100 (0% - 1.00%)")
    return int(fee_bps) * 10


def bps_to_max_fee_rate_str(fee_bps: int) -> str:
    """Format basis points as Hyperliquid ApproveBuilderFee percent string (e.g. 5 -> '0.05%')."""
    if fee_bps < 0 or fee_bps > 100:
        raise ValueError("Spot builder fee_bps must be between 0 and 100 (0% - 1.00%)")
    pct = fee_bps / 100.0
    formatted = f"{pct:.4f}".rstrip("0").rstrip(".")
    return f"{formatted}%"


def round_size(sz: float, sz_decimals: int) -> float:
    """Round order size down to the asset's exact szDecimals."""
    if sz <= 0:
        return 0.0
    factor = 10 ** sz_decimals
    return math.floor(sz * factor + 1e-12) / factor


def round_spot_price(px: float, sz_decimals: int = 2) -> float:
    """
    Round price according to Hyperliquid Spot tick rules:
    - Maximum 5 significant figures (unless integer).
    - Maximum (8 - sz_decimals) decimal places for spot markets.
    """
    if px <= 0:
        raise ValueError("Price must be > 0")
    max_decimals = max(0, 8 - sz_decimals)
    if px >= 100_000:
        return float(round(px))
    sig_decimals = 5 - int(math.floor(math.log10(abs(px)))) - 1
    decimals = max(0, min(max_decimals, sig_decimals))
    return round(px, decimals)


def hl_info_post(payload: Dict[str, Any], base_url: str = HL_MAINNET_API, timeout: int = 10) -> Any:
    """Call Hyperliquid public /info endpoint."""
    url = f"{base_url.rstrip('/')}/info"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve_spot_pair(coin_input: str, spot_meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve user-friendly symbols ('HYPE', 'HYPE/USDC', '@107', 'PURR/USDC')
    into Hyperliquid's canonical spot universe name and base token metadata.
    """
    raw = coin_input.strip()
    upper = raw.upper()
    tokens = {t["index"]: t for t in spot_meta.get("tokens", [])}

    # 1. Exact universe name match (e.g. '@107' or 'PURR/USDC')
    for pair in spot_meta.get("universe", []):
        if pair.get("name", "").upper() == upper:
            base = tokens[pair["tokens"][0]]
            quote = tokens[pair["tokens"][1]]
            return {
                "coin": pair["name"],
                "base_name": base["name"],
                "quote_name": quote["name"],
                "sz_decimals": int(base.get("szDecimals", 2)),
            }

    # 2. Match 'BASE/QUOTE' or 'BASE' (default quote USDC)
    if "/" in upper:
        want_base, want_quote = upper.split("/", 1)
    else:
        want_base, want_quote = upper, "USDC"

    for pair in spot_meta.get("universe", []):
        base = tokens.get(pair["tokens"][0], {})
        quote = tokens.get(pair["tokens"][1], {})
        if base.get("name", "").upper() == want_base and quote.get("name", "").upper() == want_quote:
            return {
                "coin": pair["name"],
                "base_name": base["name"],
                "quote_name": quote["name"],
                "sz_decimals": int(base.get("szDecimals", 2)),
            }

    raise ValueError(
        f"Spot pair '{coin_input}' not found on Hyperliquid. "
        "Try e.g. 'HYPE/USDC', '@107', 'UBTC/USDC', '@142', or 'PURR/USDC'."
    )


def fetch_spot_market_info(coin: str, base_url: str = HL_MAINNET_API) -> Dict[str, Any]:
    """Fetch canonical spot coin ID, szDecimals, and live bid/ask/mid."""
    meta = hl_info_post({"type": "spotMeta"}, base_url=base_url)
    resolved = resolve_spot_pair(coin, meta)
    canonical_coin = resolved["coin"]

    l2 = hl_info_post({"type": "l2Book", "coin": canonical_coin}, base_url=base_url)
    levels = l2.get("levels", [[], []])
    if not levels or not levels[0] or not levels[1]:
        raise ValueError(f"Empty order book returned for {canonical_coin}")
    bid = float(levels[0][0]["px"])
    ask = float(levels[1][0]["px"])
    return {
        "coin": canonical_coin,
        "base_name": resolved["base_name"],
        "quote_name": resolved["quote_name"],
        "sz_decimals": resolved["sz_decimals"],
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2.0,
    }


def fetch_spot_mid_price(coin: str, base_url: str = HL_MAINNET_API) -> float:
    """Fetch current spot mid price from Hyperliquid public /info endpoint."""
    return fetch_spot_market_info(coin, base_url=base_url)["mid"]


def fetch_spot_available_balances(account_address: str, base_url: str = HL_MAINNET_API) -> Dict[str, float]:
    """Return available (total - hold) Spot balances by token symbol."""
    spot_state = hl_info_post(
        {"type": "spotClearinghouseState", "user": account_address},
        base_url=base_url,
    )
    available: Dict[str, float] = {}
    for b in spot_state.get("balances", []):
        coin = b.get("coin")
        total = float(b.get("total", 0.0) or 0.0)
        hold = float(b.get("hold", 0.0) or 0.0)
        if coin:
            available[coin] = max(0.0, total - hold)
    return available


def filter_orders_by_spot_balances(
    buy_orders: List[Dict[str, Any]],
    sell_orders: List[Dict[str, Any]],
    usdc_available: float,
    base_available: float,
) -> Dict[str, Any]:
    """
    Select only orders funded by current Spot balances (closest to market price first).
    Allows starting cleanly with 100% USDC: buys deploy below market, and sells appear
    automatically as buys fill.
    """
    funded_buys: List[Dict[str, Any]] = []
    skipped_buys = 0
    rem_usdc = usdc_available
    # Closest buy orders to current market price first (highest limit_px first)
    for o in sorted(buy_orders, key=lambda x: x["limit_px"], reverse=True):
        needed_usdc = o["sz"] * o["limit_px"]
        if needed_usdc <= rem_usdc + 1e-9:
            funded_buys.append(o)
            rem_usdc -= needed_usdc
        else:
            skipped_buys += 1

    funded_sells: List[Dict[str, Any]] = []
    skipped_sells = 0
    rem_base = base_available
    # Closest sell orders to current market price first (lowest limit_px first)
    for o in sorted(sell_orders, key=lambda x: x["limit_px"]):
        needed_base = o["sz"]
        if needed_base <= rem_base + 1e-12:
            funded_sells.append(o)
            rem_base -= needed_base
        else:
            skipped_sells += 1

    return {
        "buy_orders": sorted(funded_buys, key=lambda x: x["limit_px"]),
        "sell_orders": sorted(funded_sells, key=lambda x: x["limit_px"]),
        "skipped_buys": skipped_buys,
        "skipped_sells": skipped_sells,
    }


def check_builder_status(builder_address: str = DEFAULT_BUILDER_WALLET, base_url: str = HL_MAINNET_API) -> Dict[str, Any]:
    """
    Verify whether a builder address satisfies Hyperliquid's HIP-1 requirements:
    1. Account abstraction mode must be 'standard' / 'default' / 'disabled' (NOT 'unifiedAccount').
    2. Perps account value must be >= 100 USDC.
    """
    perp_state = hl_info_post({"type": "clearinghouseState", "user": builder_address}, base_url=base_url)
    spot_state = hl_info_post({"type": "spotClearinghouseState", "user": builder_address}, base_url=base_url)
    abstraction = hl_info_post({"type": "userAbstraction", "user": builder_address}, base_url=base_url)

    perp_val = float(perp_state.get("marginSummary", {}).get("accountValue", 0.0) or 0.0)
    spot_usdc = 0.0
    for b in spot_state.get("balances", []):
        if b.get("coin") == "USDC":
            spot_usdc = float(b.get("total", 0.0) or 0.0)
            break

    is_standard_mode = str(abstraction).lower() not in ("unifiedaccount", "portfoliomargin")
    has_min_perp = perp_val >= 100.0
    return {
        "builder": builder_address.lower(),
        "abstraction_mode": abstraction,
        "is_standard_mode": is_standard_mode,
        "perp_account_value": perp_val,
        "spot_usdc": spot_usdc,
        "has_min_perp_usdc": has_min_perp,
        "eligible": is_standard_mode and has_min_perp,
    }


def calculate_grid_levels(
    lower: float,
    upper: float,
    n_levels: int,
    mode: str = "geometric",
    sz_decimals: Optional[int] = None,
) -> List[float]:
    """Calculate price points for the grid, optionally rounded to Hyperliquid Spot tick rules."""
    if n_levels < 2:
        raise ValueError("n_levels must be >= 2")
    if lower <= 0 or upper <= lower:
        raise ValueError("Invalid lower/upper bounds")

    if mode == "geometric":
        ratio = (upper / lower) ** (1.0 / (n_levels - 1))
        raw = [lower * (ratio ** i) for i in range(n_levels)]
    elif mode == "arithmetic":
        step = (upper - lower) / (n_levels - 1)
        raw = [lower + i * step for i in range(n_levels)]
    else:
        raise ValueError(f"Unknown grid mode: {mode}")

    if sz_decimals is not None:
        return [round_spot_price(p, sz_decimals=sz_decimals) for p in raw]
    return [round(p, 6) for p in raw]


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


def to_sdk_order_request(order: Dict[str, Any]) -> Dict[str, Any]:
    """Strip builder key for hyperliquid-python-sdk bulk_orders (builder is passed separately)."""
    return {
        "coin": order["coin"],
        "is_buy": order["is_buy"],
        "sz": order["sz"],
        "limit_px": order["limit_px"],
        "order_type": order["order_type"],
        "reduce_only": order["reduce_only"],
    }


def generate_initial_grid_orders(
    coin: str,
    levels: List[float],
    current_price: float,
    total_capital: float,
    fee_bps: int = DEFAULT_FEE_BPS,
    builder_address: str = DEFAULT_BUILDER_WALLET,
    sz_decimals: int = 4,
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
            "below_min_notional": False,
        }

    usd_per_order = total_capital / total_orders
    below_min = usd_per_order < MIN_ORDER_NOTIONAL_USD

    buy_orders = []
    for px in buy_levels:
        sz = round_size(usd_per_order / px, sz_decimals)
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
        sz = round_size(usd_per_order / px, sz_decimals)
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
        "below_min_notional": below_min,
    }


def find_nearest_level_index(levels: List[float], price: float) -> int:
    """Find the grid level index closest to a filled execution price."""
    return min(range(len(levels)), key=lambda i: abs(levels[i] - price))


def compute_counter_order_on_fill(
    coin: str,
    levels: List[float],
    fill_is_buy: bool,
    fill_price: float,
    fill_sz: float,
    sz_decimals: int = 2,
    fee_bps: int = DEFAULT_FEE_BPS,
    builder_address: str = DEFAULT_BUILDER_WALLET,
) -> Optional[Dict[str, Any]]:
    """
    Core Grid Rebalancing Rule:
    - If a BUY filled at level i -> place a SELL at level i + 1 for the same base size.
    - If a SELL filled at level i -> place a BUY at level i - 1 for the same base size.
    Returns None if the fill occurred at the boundary level where no counter-level exists.
    """
    idx = find_nearest_level_index(levels, fill_price)
    if fill_is_buy:
        target_idx = idx + 1
        if target_idx >= len(levels):
            return None
        target_is_buy = False
    else:
        target_idx = idx - 1
        if target_idx < 0:
            return None
        target_is_buy = True

    target_px = round_spot_price(levels[target_idx], sz_decimals=sz_decimals)
    target_sz = round_size(fill_sz, sz_decimals)
    if target_sz <= 0 or target_sz * target_px < MIN_ORDER_NOTIONAL_USD:
        return None

    return create_grid_order(
        coin=coin,
        is_buy=target_is_buy,
        sz=target_sz,
        px=target_px,
        fee_bps=fee_bps,
        builder_address=builder_address,
    )


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
    if plan.get("below_min_notional"):
        lines.append("")
        lines.append(
            f"[WARNING] Per-order allocation (${plan['usd_per_order']:.2f}) is below "
            f"Hyperliquid's ${MIN_ORDER_NOTIONAL_USD:.2f} minimum order value. "
            "Reduce --grids or increase --capital before running live."
        )
    lines.append("==================================================================")
    return "\n".join(lines)


def resolve_reference_price(
    coin: str,
    lower: float,
    upper: float,
    explicit_price: Optional[float] = None,
    use_live_price: bool = False,
    base_url: str = HL_MAINNET_API,
) -> float:
    """Resolve reference market price from explicit input, live L2 book, or range midpoint."""
    if explicit_price is not None:
        if explicit_price <= 0:
            raise ValueError("Reference price must be > 0")
        return explicit_price
    if use_live_price:
        return fetch_spot_mid_price(coin, base_url=base_url)
    return (lower + upper) / 2.0


class GridBotRunner:
    """
    Live non-custodial execution engine for the Hyperliquid Spot Grid Bot.
    Dependencies (`info`, `exchange`) are injectable for deterministic unit testing.
    """

    def __init__(
        self,
        info: Any,
        exchange: Any,
        account_address: str,
        coin: str,
        levels: List[float],
        capital: float,
        base_name: str = "",
        sz_decimals: int = 2,
        fee_bps: int = DEFAULT_FEE_BPS,
        builder_address: str = DEFAULT_BUILDER_WALLET,
        state_file: str = "grid_state.json",
        base_url: str = HL_MAINNET_API,
    ):
        self.info = info
        self.exchange = exchange
        self.account_address = account_address.lower()
        self.coin = coin
        self.base_name = base_name
        self.levels = sorted(levels)
        self.capital = capital
        self.sz_decimals = sz_decimals
        self.fee_bps = fee_bps
        self.builder_address = builder_address.lower()
        self.builder_payload = {
            "b": self.builder_address,
            "f": bps_to_hl_builder_f(fee_bps),
        }
        self.state_file = state_file
        self.base_url = base_url
        self.processed_tids: set = set()
        self._load_state()

    def _load_state(self) -> None:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.processed_tids = set(data.get("processed_tids", []))
            except (OSError, json.JSONDecodeError):
                self.processed_tids = set()

    def _save_state(self) -> None:
        payload = {
            "coin": self.coin,
            "account": self.account_address,
            "levels": self.levels,
            "processed_tids": sorted(self.processed_tids)[-500:],
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def verify_builder_approval(self) -> Tuple[bool, int]:
        """Check whether account_address has approved >= fee_bps for builder_address."""
        approved_f = hl_info_post(
            {
                "type": "maxBuilderFee",
                "user": self.account_address,
                "builder": self.builder_address,
            },
            base_url=self.base_url,
        )
        approved_int = int(approved_f or 0)
        required_f = self.builder_payload["f"]
        return approved_int >= required_f, approved_int

    def deploy_initial_grid(
        self,
        current_price: float,
        available_balances: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Place the initial set of Post-Only grid orders funded by current Spot balances."""
        plan = generate_initial_grid_orders(
            coin=self.coin,
            levels=self.levels,
            current_price=current_price,
            total_capital=self.capital,
            fee_bps=self.fee_bps,
            builder_address=self.builder_address,
            sz_decimals=self.sz_decimals,
        )
        if plan["below_min_notional"]:
            raise ValueError(
                f"Per-order value (${plan['usd_per_order']:.2f}) is below "
                f"Hyperliquid minimum (${MIN_ORDER_NOTIONAL_USD:.2f})."
            )

        skipped_buys = 0
        skipped_sells = 0
        if available_balances is not None:
            filtered = filter_orders_by_spot_balances(
                buy_orders=plan["buy_orders"],
                sell_orders=plan["sell_orders"],
                usdc_available=available_balances.get("USDC", 0.0),
                base_available=available_balances.get(self.base_name, 0.0),
            )
            plan["buy_orders"] = filtered["buy_orders"]
            plan["sell_orders"] = filtered["sell_orders"]
            skipped_buys = filtered["skipped_buys"]
            skipped_sells = filtered["skipped_sells"]

        all_orders = plan["buy_orders"] + plan["sell_orders"]
        if not all_orders:
            raise ValueError(
                "No orders could be placed with current Spot balances. "
                "Ensure you have enough Spot USDC (for buy levels) or base asset (for sell levels)."
            )

        # Seed processed_tids with existing fills so we only react to NEW fills after startup
        existing_fills = self.info.user_fills(self.account_address) or []
        for f in existing_fills:
            if f.get("coin") == self.coin and f.get("tid") is not None:
                self.processed_tids.add(f["tid"])
        self._save_state()

        sdk_orders = [to_sdk_order_request(o) for o in all_orders]
        res = self.exchange.bulk_orders(sdk_orders, builder=self.builder_payload)
        return {
            "plan": plan,
            "skipped_buys": skipped_buys,
            "skipped_sells": skipped_sells,
            "exchange_response": res,
        }

    def sync_fills_once(self) -> List[Dict[str, Any]]:
        """Poll recent fills for this coin and submit counter-orders on adjacent grid levels."""
        fills = self.info.user_fills(self.account_address) or []
        placed: List[Dict[str, Any]] = []

        coin_fills = [f for f in fills if f.get("coin") == self.coin]
        coin_fills.sort(key=lambda x: x.get("time", 0))

        for fill in coin_fills:
            tid = fill.get("tid")
            if tid is None or tid in self.processed_tids:
                continue

            side_str = str(fill.get("side", "")).upper()
            fill_is_buy = side_str == "B"
            fill_px = float(fill["px"])
            fill_sz = float(fill["sz"])

            counter = compute_counter_order_on_fill(
                coin=self.coin,
                levels=self.levels,
                fill_is_buy=fill_is_buy,
                fill_price=fill_px,
                fill_sz=fill_sz,
                sz_decimals=self.sz_decimals,
                fee_bps=self.fee_bps,
                builder_address=self.builder_address,
            )

            self.processed_tids.add(tid)
            if counter is None:
                continue

            resp = self.exchange.order(
                name=counter["coin"],
                is_buy=counter["is_buy"],
                sz=counter["sz"],
                limit_px=counter["limit_px"],
                order_type=counter["order_type"],
                reduce_only=False,
                builder=self.builder_payload,
            )
            placed.append({"fill_tid": tid, "counter_order": counter, "response": resp})

        if placed or coin_fills:
            self._save_state()
        return placed

    def cancel_all_coin_orders(self) -> int:
        """Cancel all open orders on this spot pair."""
        open_orders = self.info.open_orders(self.account_address) or []
        cancelled = 0
        for o in open_orders:
            if o.get("coin") == self.coin and o.get("oid") is not None:
                self.exchange.cancel(self.coin, int(o["oid"]))
                cancelled += 1
        return cancelled


def _build_sdk_clients(private_key: str, account_address: Optional[str], base_url: str):
    """Instantiate Hyperliquid SDK Info and Exchange clients from a private key."""
    try:
        from eth_account import Account
        from hyperliquid.exchange import Exchange
        from hyperliquid.info import Info
    except ImportError as exc:
        raise RuntimeError(
            "Missing live dependencies. Run: pip install -r requirements.txt"
        ) from exc

    wallet = Account.from_key(private_key)
    resolved_account = (account_address or wallet.address).lower()
    info = Info(base_url=base_url, skip_ws=True)
    exchange = Exchange(
        wallet,
        base_url=base_url,
        account_address=resolved_account if resolved_account != wallet.address.lower() else None,
    )
    return info, exchange, resolved_account


def run_approve_builder(fee_bps: int, base_url: str) -> None:
    """Sign and submit one-time ApproveBuilderFee using HL_MAIN_PRIVATE_KEY."""
    main_key = os.environ.get("HL_MAIN_PRIVATE_KEY", "").strip()
    if not main_key:
        print(
            "[ERROR] HL_MAIN_PRIVATE_KEY environment variable is required for --approve-builder.\n"
            "Hyperliquid requires ApproveBuilderFee to be signed once by your MAIN wallet "
            "(not an API/Agent wallet).\n"
            "Example:\n"
            "  export HL_MAIN_PRIVATE_KEY=0x...\n"
            "  python spot_grid_bot.py --approve-builder --fee-bps 5",
            file=sys.stderr,
        )
        sys.exit(1)

    _, exchange, account = _build_sdk_clients(main_key, None, base_url)
    max_rate = bps_to_max_fee_rate_str(fee_bps)
    print(f"Approving builder {DEFAULT_BUILDER_WALLET} up to {max_rate} for main wallet {account}...")
    resp = exchange.approve_builder_fee(builder=DEFAULT_BUILDER_WALLET, max_fee_rate=max_rate)
    print("Hyperliquid response:", json.dumps(resp, indent=2))


def run_check_builder(base_url: str) -> None:
    """Print protocol eligibility report for the project builder address."""
    st = check_builder_status(builder_address=DEFAULT_BUILDER_WALLET, base_url=base_url)
    print("==================================================================")
    print("  HYPERLIQUID BUILDER CODE ELIGIBILITY CHECK (HIP-1)")
    print("==================================================================")
    print(f"Builder Address:       {st['builder']}")
    print(f"Account Mode:          {st['abstraction_mode']} ({'OK' if st['is_standard_mode'] else 'MUST BE Manual/standard'})")
    print(f"Perp Account Value:    ${st['perp_account_value']:,.2f} USDC (Requires >= $100.00)")
    print(f"Spot USDC Balance:     ${st['spot_usdc']:,.2f} USDC")
    print(f"Builder Eligible Now:  {'YES' if st['eligible'] else 'NO'}")
    if not st["is_standard_mode"]:
        print("\n[ACTION REQUIRED] Switch Account Type to Manual (Standard) in Hyperliquid Portfolio")
        print("                  to collect Builder Fees.")
    if not st["has_min_perp_usdc"]:
        missing = max(0.0, 100.0 - st["perp_account_value"])
        print(f"\n[ACTION REQUIRED] Hold at least $100.00 USDC in Perps (missing ${missing:,.2f} USDC).")
    print("==================================================================")


def run_live_bot(args: argparse.Namespace, base_url: str) -> None:
    """Execute live grid trading loop using HL_PRIVATE_KEY (API/Agent wallet recommended)."""
    priv_key = os.environ.get("HL_PRIVATE_KEY", "").strip()
    account_addr = os.environ.get("HL_ACCOUNT_ADDRESS", "").strip() or None
    if not priv_key:
        print(
            "[ERROR] HL_PRIVATE_KEY environment variable is required for --run.\n"
            "For security, create a Hyperliquid API Wallet (Agent) with NO withdrawal permissions:\n"
            "  export HL_PRIVATE_KEY=0x<agent_private_key>\n"
            "  export HL_ACCOUNT_ADDRESS=0x<your_main_wallet_address>\n"
            "  python spot_grid_bot.py --run --coin HYPE/USDC --lower 50 --upper 80 --grids 8 --capital 100",
            file=sys.stderr,
        )
        sys.exit(1)

    market = fetch_spot_market_info(args.coin, base_url=base_url)
    canonical_coin = market["coin"]
    base_name = market["base_name"]
    sz_decimals = market["sz_decimals"]
    current_price = market["mid"]
    levels = calculate_grid_levels(
        args.lower, args.upper, args.grids, mode=args.mode, sz_decimals=sz_decimals
    )

    info, exchange, resolved_account = _build_sdk_clients(priv_key, account_addr, base_url)
    runner = GridBotRunner(
        info=info,
        exchange=exchange,
        account_address=resolved_account,
        coin=canonical_coin,
        base_name=base_name,
        levels=levels,
        capital=args.capital,
        sz_decimals=sz_decimals,
        fee_bps=args.fee_bps,
        builder_address=DEFAULT_BUILDER_WALLET,
        state_file=args.state_file,
        base_url=base_url,
    )

    if args.fee_bps > 0:
        ok, approved_f = runner.verify_builder_approval()
        if not ok:
            print(
                f"[ERROR] Wallet {resolved_account} has approved f={approved_f} for builder "
                f"{DEFAULT_BUILDER_WALLET}, but this run requires f={bps_to_hl_builder_f(args.fee_bps)} "
                f"({args.fee_bps} bps).\n"
                "Run once with your main wallet:\n"
                f"  HL_MAIN_PRIVATE_KEY=0x... python spot_grid_bot.py --approve-builder --fee-bps {args.fee_bps}",
                file=sys.stderr,
            )
            sys.exit(1)

    balances = fetch_spot_available_balances(resolved_account, base_url=base_url)
    print(
        f"Live market {base_name}/USDC ({canonical_coin}): mid={current_price:.4f}, "
        f"szDecimals={sz_decimals} | Spot Available: "
        f"{balances.get('USDC', 0.0):.2f} USDC, {balances.get(base_name, 0.0):.5f} {base_name}"
    )

    deployed = runner.deploy_initial_grid(current_price=current_price, available_balances=balances)
    if deployed["skipped_sells"] > 0:
        print(
            f"[INFO] Skipped {deployed['skipped_sells']} upper SELL level(s) due to insufficient "
            f"{base_name} balance — upper SELL orders will be placed automatically as BUY orders fill."
        )
    if deployed["skipped_buys"] > 0:
        print(
            f"[INFO] Skipped {deployed['skipped_buys']} lower BUY level(s) due to available Spot USDC."
        )
    print(format_grid_plan(deployed["plan"], f"{base_name}/USDC ({canonical_coin})", current_price))
    print("Initial deployment response:", json.dumps(deployed["exchange_response"], indent=2))

    stop_flag = {"stop": False}

    def _handle_sig(_signum, _frame):
        stop_flag["stop"] = True

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    print(f"\nMonitoring fills every {args.poll_interval}s... Press Ctrl+C to stop.")
    while not stop_flag["stop"]:
        try:
            rebalanced = runner.sync_fills_once()
            for item in rebalanced:
                co = item["counter_order"]
                side = "BUY" if co["is_buy"] else "SELL"
                print(
                    f"[REBALANCE] Fill tid={item['fill_tid']} -> placed {side} "
                    f"{co['sz']} {co['coin']} @ {co['limit_px']}"
                )
        except Exception as exc:
            print(f"[WARN] Poll error: {exc}", file=sys.stderr)

        for _ in range(max(1, int(args.poll_interval))):
            if stop_flag["stop"]:
                break
            time.sleep(1)

    if args.cancel_on_exit:
        n = runner.cancel_all_coin_orders()
        print(f"Cancelled {n} open order(s) for {canonical_coin} on exit.")
    print("Shutdown complete.")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hyperliquid Spot Grid Trading Bot (Non-Custodial)")
    parser.add_argument("--coin", type=str, default="HYPE/USDC", help="Spot pair (e.g. HYPE/USDC, @107, UBTC/USDC, PURR/USDC)")
    parser.add_argument("--lower", type=float, default=50.0, help="Lower price boundary (USD)")
    parser.add_argument("--upper", type=float, default=80.0, help="Upper price boundary (USD)")
    parser.add_argument("--grids", type=int, default=8, help="Number of grid levels")
    parser.add_argument("--mode", type=str, default="geometric", choices=["geometric", "arithmetic"], help="Grid distribution mode")
    parser.add_argument("--capital", type=float, default=100.0, help="Total USD capital to deploy in grid")
    parser.add_argument("--price", type=float, default=None, help="Override reference market price (USD) in --plan mode")
    parser.add_argument("--live-price", action="store_true", help="Fetch live spot mid price & szDecimals from Hyperliquid public API")
    parser.add_argument("--fee-bps", type=int, default=DEFAULT_FEE_BPS, help="Builder fee in bps (default 5 = 0.05%%)")
    parser.add_argument("--testnet", action="store_true", help="Use Hyperliquid Testnet instead of Mainnet")
    parser.add_argument("--poll-interval", type=int, default=10, help="Seconds between fill checks in --run mode")
    parser.add_argument("--state-file", type=str, default="grid_state.json", help="Path to local state file")
    parser.add_argument("--cancel-on-exit", action="store_true", help="Cancel open grid orders on Ctrl+C")

    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--plan", action="store_true", help="Print grid plan and exit (dry-run mode, default)")
    action_group.add_argument("--check-builder", action="store_true", help="Check Hyperliquid HIP-1 eligibility for builder wallet")
    action_group.add_argument("--approve-builder", action="store_true", help="Sign one-time ApproveBuilderFee using HL_MAIN_PRIVATE_KEY")
    action_group.add_argument("--run", action="store_true", help="Run live grid bot using HL_PRIVATE_KEY (API/Agent wallet)")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    base_url = HL_TESTNET_API if args.testnet else HL_MAINNET_API

    if args.check_builder:
        run_check_builder(base_url=base_url)
        return

    if args.approve_builder:
        run_approve_builder(args.fee_bps, base_url=base_url)
        return

    if args.run:
        run_live_bot(args, base_url=base_url)
        return

    # Default: --plan dry-run mode
    sz_decimals = 4
    display_coin = args.coin
    if args.live_price:
        market = fetch_spot_market_info(args.coin, base_url=base_url)
        sz_decimals = market["sz_decimals"]
        display_coin = f"{market['base_name']}/USDC ({market['coin']})"
        current_price = args.price if args.price is not None else market["mid"]
        levels = calculate_grid_levels(
            args.lower, args.upper, args.grids, mode=args.mode, sz_decimals=sz_decimals
        )
    else:
        levels = calculate_grid_levels(args.lower, args.upper, args.grids, mode=args.mode)
        current_price = resolve_reference_price(
            coin=args.coin,
            lower=args.lower,
            upper=args.upper,
            explicit_price=args.price,
            use_live_price=False,
            base_url=base_url,
        )

    plan = generate_initial_grid_orders(
        coin=args.coin,
        levels=levels,
        current_price=current_price,
        total_capital=args.capital,
        fee_bps=args.fee_bps,
        builder_address=DEFAULT_BUILDER_WALLET,
        sz_decimals=sz_decimals,
    )
    print(format_grid_plan(plan, display_coin, current_price))


if __name__ == "__main__":
    main()
