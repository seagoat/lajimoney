# 交易成本配置 + 裸套模式 设计文档

> **Goal:** 在设置页面支持自定义交易成本（券商佣金、印花税、CB佣金），并支持底仓为空时启用裸套模式（无底仓纯做多 + 转股持有）

## 1. 数据模型变更

### 1.1 settings 表新增字段

| key | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `stock_broker_fee` | TEXT (存小数) | `0.0001` | 股票券商佣金（万1 = 0.01%），买卖均收 |
| `stock_stamp_tax` | TEXT | `0.0015` | 股票印花税（千1.5 = 0.15%），仅卖出收取 |
| `cb_broker_fee` | TEXT | `0.00006` | 转债券商佣金（万0.6 = 0.006%），买卖均收 |
| `naked_discount_threshold` | TEXT | `-2.0` | 裸套折价阈值（溢价率 < 此值才触发），单位 % |
| `naked_enabled` | TEXT | `true` | 是否启用裸套模式（布尔值） |

### 1.2 trades 表新增列

```sql
ALTER TABLE trades ADD COLUMN trade_type TEXT DEFAULT 'HEDGE';
-- 'HEDGE' = 持仓对冲模式（已有底仓）
-- 'NAKED' = 裸套模式（无底仓纯做多转股）
```

### 1.3 models.py 变更

**SettingsResponse** 增加字段：
```python
class SettingsResponse(BaseModel):
    discount_threshold: float
    target_lot_size: int
    scan_mode: str
    stock_broker_fee: float
    stock_stamp_tax: float
    cb_broker_fee: float
    naked_discount_threshold: float
    naked_enabled: bool
```

**SettingsUpdate** 增加字段：
```python
class SettingsUpdate(BaseModel):
    discount_threshold: Optional[float] = None
    target_lot_size: Optional[int] = None
    scan_mode: Optional[str] = None
    stock_broker_fee: Optional[float] = None
    stock_stamp_tax: Optional[float] = None
    cb_broker_fee: Optional[float] = None
    naked_discount_threshold: Optional[float] = None
    naked_enabled: Optional[bool] = None
```

---

## 2. 扫描逻辑变更

### 2.1 scan_all_cb_gen 修改

在生成器开始扫描前：
1. 调用 `load_holdings()` 检查底仓是否为空
2. **底仓非空**：使用 `discount_threshold`（普通阈值），`trade_type = 'HEDGE'`
3. **底仓为空 + naked_enabled=true**：使用 `naked_discount_threshold`，`trade_type = 'NAKED'`
4. **底仓为空 + naked_enabled=false**：yield 一条 `no_holdings` 状态，直接结束

扫描结果中的信号 dict 增加 `trade_type` 字段。

### 2.2 signal_engine.py 新增辅助函数

```python
def calc_net_profit_hedge(buy_price, buy_shares, sell_price, conversion_price,
                          stock_broker_fee, stock_stamp_tax, cb_broker_fee) -> dict:
    """计算持仓对冲模式净收益"""
    buy_amount = buy_price * 100 * buy_shares
    sell_amount = sell_price * 100 * buy_shares
    # 佣金和印花税
    stock_commission = sell_amount * stock_broker_fee  # 卖出股票佣金
    stamp_tax = sell_amount * stock_stamp_tax          # 印花税
    cb_buy_commission = buy_amount * cb_broker_fee
    cb_sell_commission = sell_amount * cb_broker_fee
    net_profit = sell_amount - buy_amount - stock_commission - stamp_tax - cb_buy_commission - cb_sell_commission
    return net_profit, round(net_profit / buy_amount * 100, 4)


def calc_net_profit_naked(buy_price, buy_shares, cb_price, sell_price_open,
                          conversion_price, stock_broker_fee, cb_broker_fee) -> dict:
    """计算裸套模式净收益（CB买入 → 转股 → 次日卖出）"""
    cb_buy_amount = buy_price * 100 * buy_shares
    cb_buy_commission = cb_buy_amount * cb_broker_fee
    total_cost = cb_buy_amount + cb_buy_commission

    # 转股：每张CB转股数为 100/conversion_price
    shares_from_cb = (100.0 / conversion_price) * buy_shares
    # 次日卖出：使用模拟开盘价（简化：sell_price_open）
    sell_stock_amount = sell_price_open * shares_from_cb
    stock_commission = sell_stock_amount * stock_broker_fee
    cb_sell_commission = 0  # 裸套转股后无CB卖出，只有股票卖出

    net_profit = sell_stock_amount - total_cost - stock_commission
    return net_profit, round(net_profit / total_cost * 100, 4)
```

---

## 3. 平仓结算逻辑变更

### 3.1 settle_pending_trades 修改

在现有 PENDING 平仓循环中，读取 `trade_type`：
- **HEDGE**：现有逻辑不变
- **NAKED**：
  - 用 `calc_net_profit_naked()` 计算收益
  - 卖出金额用 `stock_price`（次日模拟开盘价 = 简化处理）
  - 更新 `trade_type = 'NAKED'`

---

## 4. 前端设置页面变更

### 4.1 settings.html 表单扩展

在现有表单下增加两个区块：

**交易成本区块**（3个输入框）：
- 股票券商佣金率（默认 0.0001）
- 股票印花税率（默认 0.0015，仅卖出）
- 转债券商佣金率（默认 0.00006）

**裸套模式区块**（开关 + 阈值）：
- 启用裸套模式（checkbox 或 toggle）
- 裸套折价阈值（默认 -2.0）

### 4.2 index.html 扫描结果区分

在 `done` 事件的处理中，区分 HEDGE 和 NAKED 信号显示。

---

## 5. API 变更

### GET /api/settings
返回所有 8 个字段（含新增 5 个）。

### PUT /api/settings
接受所有 8 个字段的更新。

### POST /api/signals/scan
trade_engine.py 中读取新的成本参数和裸套开关，传递给扫描器。

---

## 6. 实现顺序

1. **database.py**：ALTER TABLE trades ADD trade_type；INSERT 新 settings 默认值
2. **models.py**：扩展 SettingsResponse / SettingsUpdate
3. **signal_engine.py**：添加 calc_net_profit_hedge / calc_net_profit_naked；修改 scan_all_cb_gen 逻辑
4. **trade_engine.py**：settle_pending_trades 支持 NAKED 类型
5. **routers/settings.py**：GET/PUT 透传新字段
6. **routers/signals.py**：scan_stream 透传 cost_params 和 naked_enabled
7. **templates/settings.html**：扩展表单
8. **templates/index.html**：done 事件处理区分 trade_type
