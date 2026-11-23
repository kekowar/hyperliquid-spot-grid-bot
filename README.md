# Hyperliquid Spot Grid Bot (Non-Custodial)

[English](#english) | [中文说明](#chinese) | [Español](#español)

---

<a name="english"></a>
## English

An open-source, non-custodial Spot Grid Trading Bot built specifically for Hyperliquid Spot markets (`HYPE/USDC`, `UBTC/USDC`, `UETH/USDC`, `PURR/USDC`).

Places passive maker limit orders (*Post-Only* / `Alo`) in a structured geometric or arithmetic grid and automatically rebalances filled levels:
- **Buys dips** below current market price; when a buy fills at level `i`, automatically posts a sell at level `i + 1`.
- **Sells rallies** above current market price; when a sell fills at level `i`, automatically posts a buy at level `i - 1`.
- **Zero liquidation risk & zero perp funding costs** (100% spot market).
- **Non-custodial security:** Runs locally on your machine using a Hyperliquid **API Wallet (Agent)** that can only place/cancel orders and has **zero withdrawal permissions**.

### 1. Installation
```bash
git clone https://github.com/kekowar/hyperliquid-spot-grid-bot.git
cd hyperliquid-spot-grid-bot
pip install -r requirements.txt
```

### 2. Plan Your Grid (Dry-Run — No Keys Needed)
Preview exact tick-rounded grid levels and per-order capital before risking funds:
```bash
# Offline simulation using midpoint
python spot_grid_bot.py --plan --coin @107 --lower 50 --upper 80 --grids 8 --capital 100

# Live mid-price & szDecimals from Hyperliquid public API
python spot_grid_bot.py --plan --coin @107 --lower 20 --upper 45 --grids 8 --capital 100 --live-price
```

### 3. Live Execution Setup (2 One-Time Steps)

#### Step A: Approve the Builder Fee Once (Main Wallet)
Hyperliquid requires every user to authorize a builder's max fee cap once via an EIP-712 `ApproveBuilderFee` signature from their **Main Wallet** (you can revoke it at any time):
```bash
export HL_MAIN_PRIVATE_KEY="0x<your_main_wallet_key>"
python spot_grid_bot.py --approve-builder --fee-bps 5
unset HL_MAIN_PRIVATE_KEY
```

#### Step B: Run the Grid Bot with an API Wallet (Agent — Recommended)
Create an API Wallet in Hyperliquid (`More -> API`), then run the bot with that agent key (no withdrawal rights):
```bash
export HL_PRIVATE_KEY="0x<your_api_agent_private_key>"
export HL_ACCOUNT_ADDRESS="0x<your_main_wallet_address>"

python spot_grid_bot.py --run \
  --coin @107 \
  --lower 20 \
  --upper 45 \
  --grids 8 \
  --capital 120 \
  --poll-interval 10 \
  --cancel-on-exit
```
> **Note:** Hyperliquid enforces a **$10 USDC minimum order value** on Spot. Ensure `capital / grids >= 10` and hold both USDC (for buy levels) and base asset (for sell levels) in your Spot balance.

### 4. CLI Options
| Flag | Description | Default |
|---|---|---|
| `--plan` | Dry-run grid preview (default mode) | `True` |
| `--run` | Live deployment + automatic fill-rebalancing loop | `False` |
| `--approve-builder` | One-time EIP-712 `ApproveBuilderFee` using `HL_MAIN_PRIVATE_KEY` | `False` |
| `--check-builder` | Check HIP-1 eligibility of the builder address (`standard` mode + `>= 100 USDC` Perps) | `False` |
| `--coin` | Spot pair symbol (`@107` HYPE, `@142` UBTC, `PURR/USDC`) | `@107` |
| `--lower` / `--upper` | Price boundaries in USD | `50.0` / `80.0` |
| `--grids` | Number of grid levels | `8` |
| `--mode` | Spacing: `geometric` or `arithmetic` | `geometric` |
| `--capital` | Total USD allocated across the grid | `100.0` |
| `--live-price` | Fetch live mid price & `szDecimals` from Hyperliquid `/info` | `False` |
| `--fee-bps` | Builder fee in bps (`f = fee_bps * 10` in tenths of a bps) | `5` (0.05%) |
| `--testnet` | Run against Hyperliquid Testnet | `False` |
| `--cancel-on-exit` | Cancel open orders for this coin on `Ctrl+C` | `False` |

### 5. Protocol-Level Builder Fee (HIP-1)
This software is free and open-source under the MIT License. It monetizes via Hyperliquid's native Builder Code (`0x3f294E8CFc89B9f0Df5608D601fBaCf385E6DbEc`):
- Attaches `5 bps` (`0.05%`, protocol `f=50` in tenths of a bps) to generated orders.
- Per Hyperliquid Spot protocol rules, builder fees are collected in USDC on **sell fills** only, and only after your explicit `ApproveBuilderFee` authorization.
- Zero subscriptions, zero key exfiltration, 100% auditable code.

### 6. Tests
```bash
pytest -v
```

---

<a name="chinese"></a>
## 中文说明 (Chinese)

专为 Hyperliquid 现货市场（`HYPE/USDC`、`UBTC/USDC`、`UETH/USDC`、`PURR/USDC` 等）设计的开源、非托管网格交易机器人。

在区间内自动挂出被动限价单（Post-Only / 只做 Maker / `Alo`），并在成交后自动补挂反向网格单：
- **下跌分批买入：** 第 `i` 格买单成交后，自动在第 `i + 1` 格挂出卖单。
- **反弹分批卖出：** 第 `i` 格卖单成交后，自动在第 `i - 1` 格挂出买单。
- **无爆仓风险、无资金费率损耗：** 100% 现货市场运行。
- **非托管安全：** 在本地运行，推荐使用仅具交易权限、**无提币权限**的 Hyperliquid API Wallet（Agent 钱包）。

### 1. 安装
```bash
git clone https://github.com/kekowar/hyperliquid-spot-grid-bot.git
cd hyperliquid-spot-grid-bot
pip install -r requirements.txt
```

### 2. 模拟测算网格（Dry-Run，无需私钥）
```bash
python spot_grid_bot.py --plan --coin @107 --lower 20 --upper 45 --grids 8 --capital 100 --live-price
```

### 3. 实盘运行（仅需两步）
1. **一次性授权 Builder Fee（需主钱包签名一次，可随时撤销）：**
   ```bash
   export HL_MAIN_PRIVATE_KEY="0x<你的主钱包私钥>"
   python spot_grid_bot.py --approve-builder --fee-bps 5
   unset HL_MAIN_PRIVATE_KEY
   ```
2. **使用 API/Agent 钱包运行自动网格：**
   ```bash
   export HL_PRIVATE_KEY="0x<API_Agent_私钥>"
   export HL_ACCOUNT_ADDRESS="0x<主钱包地址>"
   python spot_grid_bot.py --run --coin @107 --lower 20 --upper 45 --grids 8 --capital 120 --cancel-on-exit
   ```

### 4. 协议原生 Builder Fee（HIP-1）
本项目采用 MIT 开源协议，通过 Hyperliquid 官方原生 Builder Code 运作（`0x3f294E8CFc89B9f0Df5608D601fBaCf385E6DbEc`）：
- 默认附带 `5 bps`（`0.05%`，协议单位 `f=50`）开发者费，依据 Hyperliquid 现货规则仅在卖单成交时以 USDC 结算。
- 零月费、无托管风险、代码完全开源透明。

---

<a name="español"></a>
## Español

Bot de Grid Trading de código abierto y no custodial diseñado específicamente para los mercados Spot de Hyperliquid (`HYPE/USDC`, `UBTC/USDC`, `UETH/USDC`, `PURR/USDC`).

Coloca órdenes limitadas pasivas *Post-Only* (`Alo`) en una rejilla geométrica o aritmética y repone automáticamente cada nivel al ejecutarse:
- **Compra en caídas:** cuando se llena una compra en el nivel `i`, coloca automáticamente una venta en el nivel `i + 1`.
- **Vende en rebotes:** cuando se llena una venta en el nivel `i`, coloca automáticamente una compra en el nivel `i - 1`.
- **Sin liquidaciones ni costes de financiación** (100% mercado Spot).
- **Seguridad no custodial:** corre en tu propio equipo usando una **API Wallet (Agent)** de Hyperliquid que solo puede operar y **no tiene permiso para retirar fondos**.

### 1. Instalación
```bash
git clone https://github.com/kekowar/hyperliquid-spot-grid-bot.git
cd hyperliquid-spot-grid-bot
pip install -r requirements.txt
```

### 2. Simular tu Rejilla (Dry-Run, sin claves)
```bash
python spot_grid_bot.py --plan --coin @107 --lower 20 --upper 45 --grids 8 --capital 100 --live-price
```

### 3. Puesta en Marcha en Vivo (2 pasos)
1. **Aprobar el Builder Fee una sola vez (con tu Main Wallet):**
   ```bash
   export HL_MAIN_PRIVATE_KEY="0x<clave_de_tu_main_wallet>"
   python spot_grid_bot.py --approve-builder --fee-bps 5
   unset HL_MAIN_PRIVATE_KEY
   ```
2. **Ejecutar el Grid Bot con una API Wallet (Agent sin permisos de retiro):**
   ```bash
   export HL_PRIVATE_KEY="0x<clave_api_agent>"
   export HL_ACCOUNT_ADDRESS="0x<tu_direccion_main_wallet>"
   python spot_grid_bot.py --run --coin @107 --lower 20 --upper 45 --grids 8 --capital 120 --cancel-on-exit
   ```

> **Nota:** Hyperliquid exige un mínimo de **$10 USDC por orden** en Spot (`capital / grids >= 10`).

### 4. Comisión Nativa de Constructor (HIP-1 Builder Fee)
Software libre bajo licencia MIT que utiliza el mecanismo nativo de Hyperliquid (`0x3f294E8CFc89B9f0Df5608D601fBaCf385E6DbEc`):
- Adjunta `5 pb` (`0,05%`, campo de protocolo `f=50`) en las órdenes. Según las reglas de Spot de Hyperliquid, se cobra en USDC únicamente al ejecutarse órdenes de venta, tras la autorización explícita `ApproveBuilderFee`.
