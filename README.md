# Hyperliquid Spot Grid Bot (Non-Custodial)

[English](#english) | [中文说明](#chinese) | [Español](#español)

---

<a name="english"></a>
## English

An open-source, non-custodial Spot Grid Trading Bot planner and order-payload generator built specifically for Hyperliquid Spot markets (`HYPE/USDC`, `UBTC/USDC`, `UETH/USDC`, `PURR/USDC`).

Constructs passive maker limit orders (*Post-Only* / `Alo`) in a geometric or arithmetic price grid:
- **Buys dips** below the reference market price.
- **Sells rallies** above the reference market price.
- **Zero liquidation risk & zero perp funding costs** (100% spot market).
- **Non-custodial:** Your funds stay in your Hyperliquid wallet; private keys are never shared.

> **Current status (v0.1):** Dry-run grid planner, live mid-price lookup (`--live-price`), and HIP-1 builder-fee order payload generator. Automated live execution and fill-rebalancing loop are planned for the next release.

### 1. Requirements
* Python 3.10+
* Optional (for upcoming live execution & tests):
  ```bash
  pip install -r requirements.txt
  ```

### 2. Plan a Grid (Dry-Run / Simulation Mode)
Preview your exact grid levels and capital allocation without broadcasting orders:
```bash
# Example: Geometric grid on HYPE (@107) between $50 and $80 with 8 grid levels and $100 capital
python spot_grid_bot.py --plan --coin @107 --lower 50 --upper 80 --grids 8 --capital 100

# Fetch live spot mid price directly from Hyperliquid public API
python spot_grid_bot.py --plan --coin @107 --lower 20 --upper 60 --grids 8 --capital 100 --live-price
```

Sample output:
```text
==================================================================
  HYPERLIQUID SPOT GRID BOT: @107
==================================================================
Current Market Price:   65.0000
Capital Allocated:      $100.00 USD ($12.50 per order)
Builder Fee Attached:   5 bps (f=50) -> 0x3f294e8cfc89b9f0df5608d601fbacf385e6dbec

BUY ORDERS (placed below current price):
  [BUY]    0.2044 @    61.1575  (~$ 12.50)
  [BUY]    0.2186 @    57.1860  (~$ 12.50)
  [BUY]    0.2338 @    53.4724  (~$ 12.50)
  [BUY]    0.2500 @    50.0000  (~$ 12.50)
--- CURRENT PRICE: 65.0000 ---
SELL ORDERS (placed above current price):
  [SELL]   0.1911 @    65.4049  (~$ 12.50)
  [SELL]   0.1787 @    69.9471  (~$ 12.50)
  [SELL]   0.1671 @    74.8049  (~$ 12.50)
  [SELL]   0.1562 @    80.0000  (~$ 12.50)
==================================================================
```

### 3. Parameters
| Parameter | Description | Default |
|---|---|---|
| `--coin` | Spot pair symbol (`@107` for HYPE, `@142` for UBTC, `PURR/USDC`) | `@107` |
| `--lower` | Lower price bound in USD | `50.0` |
| `--upper` | Upper price bound in USD | `80.0` |
| `--grids` | Number of grid levels | `10` |
| `--capital` | Total USDC allocated to the grid | `100.0` |
| `--mode` | Grid spacing (`geometric` or `arithmetic`) | `geometric` |
| `--price` | Custom reference market price (USD) | Midpoint of range |
| `--live-price` | Fetch live mid price from Hyperliquid `/info` L2 book | `False` |
| `--fee-bps` | Hyperliquid Builder Fee in bps (protocol `f = fee_bps * 10`) | `5` (0.05%) |

### 4. Protocol-Level Builder Fee (HIP-1)
This software is free and open-source under the MIT License. It uses Hyperliquid's native Builder Code mechanism (`0x3f294E8CFc89B9f0Df5608D601fBaCf385E6DbEc`):
- A 5 bps (0.05%, protocol `f=50` in tenths of a bps) fee is attached to generated orders and settled on-chain by Hyperliquid only when orders fill (after one-time user `ApproveBuilderFee` authorization).
- No subscriptions, no custodial lock-in, completely auditable source code.

### 5. Running Tests
```bash
pytest
```

---

<a name="chinese"></a>
## 中文说明 (Chinese)

专门为 Hyperliquid 现货市场（`HYPE/USDC`、`UBTC/USDC`、`UETH/USDC`、`PURR/USDC` 等）设计的开源、非托管网格交易规划与订单构建工具。

在价格区间内生成被动限价单（Post-Only / 只做 Maker / `Alo`）：
- **下跌分批买入：** 在参考市价下方挂买单。
- **反弹分批卖出：** 在参考市价上方挂卖单。
- **无爆仓风险，无资金费率损耗：** 100% 现货市场逻辑。
- **非托管安全：** 资金始终保存在您自己的 Hyperliquid 钱包中，私钥无需交给第三方。

> **当前版本 (v0.1)：** 支持 Dry-Run 网格模拟测算、Hyperliquid 实时中间价获取（`--live-price`）以及符合协议规范的 HIP-1 Builder Fee 订单载荷构建。实盘自动挂单与成交补单循环将在后续版本推出。

### 1. 运行环境要求
* Python 3.10 或更高版本
* 安装依赖：
  ```bash
  pip install -r requirements.txt
  ```

### 2. 模拟测算网格分布（Dry-Run 模式）
在不发送任何链上订单的情况下预览网格点位与资金分配：
```bash
# 示例：以 $50 到 $80 美元区间，对 HYPE（现货代码 @107）设置 8 格，投入 100 USDC
python spot_grid_bot.py --plan --coin @107 --lower 50 --upper 80 --grids 8 --capital 100

# 从 Hyperliquid 公共 API 获取实时现货中间价
python spot_grid_bot.py --plan --coin @107 --lower 20 --upper 60 --grids 8 --capital 100 --live-price
```

### 3. 可选参数说明
| 参数 | 说明 | 默认值 |
|---|---|---|
| `--coin` | 现货资产代号（HYPE 为 `@107`，UBTC 为 `@142`，`PURR/USDC`） | `@107` |
| `--lower` | 网格最低价（美元） | `50.0` |
| `--upper` | 网格最高价（美元） | `80.0` |
| `--grids` | 网格区间层数 | `10` |
| `--capital` | 分配给网格的总资金（USDC） | `100.0` |
| `--mode` | 间距模式：等比 (`geometric`) 或等差 (`arithmetic`) | `geometric` |
| `--price` | 手动指定参考市价（美元） | 区间中点 |
| `--live-price` | 从 Hyperliquid `/info` 盘口获取实时中间价 | `False` |
| `--fee-bps` | Hyperliquid 开发者构建费率（bps，协议字段 `f = fee_bps * 10`） | `5` (0.05%) |

### 4. 协议原生开发者费机制（HIP-1 Builder Fee）
本项目采用 MIT 开源协议，通过 Hyperliquid 官方原生 Builder Code 机制运作（收款地址：`0x3f294E8CFc89B9f0Df5608D601fBaCf385E6DbEc`）：
- 默认附带 5 bps（0.05%，协议单位 `f=50` 即 0.1 bps 精度）开发者费，仅在用户完成一次性 `ApproveBuilderFee` 授权且订单实际成交时由链上自动结算。
- 零月费、无后门、代码完全开源可审计。

---

<a name="español"></a>
## Español

Herramienta de código abierto y no custodial para planificar rejillas (Grid Trading) y construir órdenes *Post-Only* (`Alo`) en los mercados Spot de Hyperliquid (`HYPE/USDC`, `UBTC/USDC`, `UETH/USDC`, `PURR/USDC`).

Genera órdenes limitadas pasivas escalonadas:
- **Compra en caídas** por debajo del precio de referencia.
- **Vende en rebotes** por encima del precio de referencia.
- **Sin liquidaciones ni costes de financiación** (100% mercado Spot).
- **No custodial:** Tus fondos permanecen en tu propia billetera de Hyperliquid.

> **Estado actual (v0.1):** Planificador en modo simulación (*dry-run*), consulta de precio medio en vivo (`--live-price`) y generador de payloads de orden con Builder Fee HIP-1. La ejecución automática en vivo y el bucle de reposición por fills llegarán en la siguiente versión.

### 1. Requisitos
* Python 3.10 o superior.
* Instalar dependencias:
  ```bash
  pip install -r requirements.txt
  ```

### 2. Planificar una Rejilla (Modo Simulación / Dry-Run)
Previsualiza la distribución exacta de niveles y capital sin enviar órdenes a la red:
```bash
python spot_grid_bot.py --plan --coin @107 --lower 50 --upper 80 --grids 8 --capital 100

# Consultar el precio medio real desde la API pública de Hyperliquid
python spot_grid_bot.py --plan --coin @107 --lower 20 --upper 60 --grids 8 --capital 100 --live-price
```

### 3. Parámetros Disponibles
| Parámetro | Descripción | Valor por Defecto |
|---|---|---|
| `--coin` | Identificador del par Spot (`@107` para HYPE, `@142` para UBTC, `PURR/USDC`) | `@107` |
| `--lower` | Límite inferior de la rejilla en USD | `50.0` |
| `--upper` | Límite superior de la rejilla en USD | `80.0` |
| `--grids` | Número de niveles de la rejilla | `10` |
| `--capital` | Capital total en USDC asignado al bot | `100.0` |
| `--mode` | Distribución de niveles (`geometric` o `arithmetic`) | `geometric` |
| `--price` | Precio de referencia manual en USD | Punto medio del rango |
| `--live-price` | Obtener el precio medio actual desde `/info` de Hyperliquid | `False` |
| `--fee-bps` | Comisión de constructor en bps (campo `f = fee_bps * 10`) | `5` (0.05%) |

### 4. Comisión Nativa de Constructor (HIP-1 Builder Fee)
El software es gratuito bajo licencia MIT y utiliza el mecanismo nativo de Builder Code de Hyperliquid (`0x3f294E8CFc89B9f0Df5608D601fBaCf385E6DbEc`):
- Cada orden incluye una comisión de 5 pb (0,05%, equivalente a `f=50` en décimas de pb según el protocolo), liquidada on-chain por Hyperliquid solo cuando la orden se ejecuta tras una única autorización `ApproveBuilderFee`.
- Sin suscripciones ni custodia de claves.
