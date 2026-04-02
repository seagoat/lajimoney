# 交易成本配置 + 裸套模式 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在设置页面支持自定义交易成本（券商佣金、印花税、CB佣金），并支持底仓为空时启用裸套模式

**Architecture:** 在现有 settings 表和 trades 表上做增量扩展；scan_all_cb_gen 内嵌裸套判断逻辑；平仓结算区分 HEDGE/NAKED 两种收益算法

**Tech Stack:** FastAPI + SQLite + aiosqlite + Jinja2 templates

---

## Task 1: 数据库迁移 — settings 默认值 + trades trade_type 列

**Files:**
- Modify: `app/database.py:79-88`

- [ ] **Step 1: 添加 ALTER TABLE 和 INSERT 默认值**

找到 `database.py` 中 `init_db()` 函数的 `INSERT OR IGNORE INTO settings` 块，在最后追加 5 条新设置：

```python
INSERT OR IGNORE INTO settings (key, value) VALUES ('stock_broker_fee', '0.0001');
INSERT OR IGNORE INTO settings (key, value) VALUES ('stock_stamp_tax', '0.0015');
INSERT OR IGNORE INTO settings (key, value) VALUES ('cb_broker_fee', '0.00006');
INSERT OR IGNORE INTO settings (key, value) VALUES ('naked_discount_threshold', '-2.0');
INSERT OR IGNORE INTO settings (key, value) VALUES ('naked_enabled', 'true');
```

然后在同一函数的 `CREATE TABLE IF NOT EXISTS trades` 的 `FOREIGN KEY` 行之后，添加：

```python
CREATE TABLE IF NOT EXISTS trades (
    ...
    profit_rate REAL,
    status TEXT DEFAULT 'PENDING',
    trade_type TEXT DEFAULT 'HEDGE',
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);
```

- [ ] **Step 2: 验证数据库迁移**

运行以下命令确认 SQLite 能正常打开数据库（DB_PATH 在 app/config.py 中定义）：

```bash
cd E:/worksrc/lajimoney && python -c "
import asyncio; from app.config import DB_PATH
import aiosqlite
async def check():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(\"SELECT value FROM settings WHERE key='stock_broker_fee'\") as c:
            row = await c.fetchone()
            print('stock_broker_fee:', row[0] if row else 'NOT FOUND')
        async with db.execute(\"PRAGMA table_info(trades)\") as c:
            cols = await c.fetchall()
            print('trade_type column:', [r[1] for r in cols])
asyncio.run(check())
"
```

Expected output:
```
stock_broker_fee: 0.0001
trade_type column: [..., 'trade_type']
```

- [ ] **Step 3: Commit**

```bash
git add app/database.py
git commit -m "feat: add cost config and naked mode settings defaults, trade_type column"
```

---

## Task 2: models.py — 扩展 SettingsResponse 和 SettingsUpdate

**Files:**
- Modify: `app/models.py:90-100`

- [ ] **Step 1: 扩展 SettingsResponse**

将 `SettingsResponse` 改为：

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

- [ ] **Step 2: 扩展 SettingsUpdate**

将 `SettingsUpdate` 改为：

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

- [ ] **Step 3: Commit**

```bash
git add app/models.py
git commit -m "feat: extend SettingsResponse and SettingsUpdate with cost and naked mode fields"
```

---

## Task 3: signal_engine.py — 收益计算函数 + 裸套模式

**Files:**
- Modify: `app/services/signal_engine.py`

- [ ] **Step 1: 在文件顶部（import 区之后，calculate_conversion_value 之前）添加两个收益计算函数**

```python
def calc_net_profit_hedge(buy_price: float, buy_shares: int, sell_price: float,
                          stock_broker_fee: float, stock_stamp_tax: float,
                          cb_broker_fee: float) -> tuple[float, float]:
    """
    持仓对冲模式净收益计算
    卖出股票 - 买入CB - 双向佣金 - 印花税
    """
    buy_amount = buy_price * 100 * buy_shares
    sell_amount = sell_price * 100 * buy_shares
    stock_commission = sell_amount * stock_broker_fee
    stamp_tax = sell_amount * stock_stamp_tax
    cb_buy_commission = buy_amount * cb_broker_fee
    cb_sell_commission = sell_amount * cb_broker_fee
    net_profit = sell_amount - buy_amount - stock_commission - stamp_tax - cb_buy_commission - cb_sell_commission
    return net_profit, round(net_profit / buy_amount * 100, 4)


def calc_net_profit_naked(buy_price: float, buy_shares: int,
                           sell_price_open: float, conversion_price: float,
                           stock_broker_fee: float, cb_broker_fee: float) -> tuple[float, float]:
    """
    裸套模式净收益计算
    CB买入 → 转股 → 次日卖出正股
    收益 = 卖出正股所得 - CB买入成本 - CB买入佣金 - 股票卖出佣金
    """
    cb_buy_amount = buy_price * 100 * buy_shares
    cb_buy_commission = cb_buy_amount * cb_broker_fee
    total_cost = cb_buy_amount + cb_buy_commission

    # 每张CB转股数 = 100 / conversion_price，总股数
    shares_from_cb = (100.0 / conversion_price) * buy_shares
    # 次日卖出正股
    sell_stock_amount = sell_price_open * shares_from_cb
    stock_commission = sell_stock_amount * stock_broker_fee

    net_profit = sell_stock_amount - total_cost - stock_commission
    return net_profit, round(net_profit / total_cost * 100, 4)
```

- [ ] **Step 2: 修改 scan_all_cb_gen 函数开头**

在 `yield {'step': 0, 'total': 0, ...}` 之后，`all_cb = await asyncio.to_thread(...)` 之前，添加底仓检测逻辑。修改 `scan_all_cb_gen` 的开头部分，在 `yield {'step': 0, 'total': 0, 'stock_code': '', 'status': 'loading_cb_list', 'message': '正在加载全量转债列表...'}` 之后：

在 `all_cb = await asyncio.to_thread(get_all_cb_with_prices)` 行之前添加：

```python
    # 检测是否裸套模式（底仓为空）
    from app.routers.signals import load_holdings
    holdings_stocks = await load_holdings()
    is_naked = (len(holdings_stocks) == 0)
    naked_enabled = settings.get("naked_enabled", "false") == "true"
    effective_threshold = float(settings.get("naked_discount_threshold", "-2.0")) if is_naked and naked_enabled else discount_threshold
    if is_naked and not naked_enabled:
        yield {
            'step': 0, 'total': 0, 'stock_code': '',
            'status': 'error',
            'message': '底仓为空且裸套模式未启用，请先添加底仓或开启裸套模式',
        }
        return
    if is_naked:
        yield {
            'step': 0, 'total': 0, 'stock_code': '',
            'status': 'loaded',
            'message': f'底仓为空，启用裸套模式（折价阈值: {effective_threshold}%）...',
        }
```

注意：`settings` 参数需要传入到 generator 中，需要修改 generator 签名。

- [ ] **Step 3: 修改 scan_all_cb_gen 函数签名以接收 settings**

将 `async def scan_all_cb_gen(discount_threshold: float, target_lot_size: int):` 改为：

```python
async def scan_all_cb_gen(discount_threshold: float, target_lot_size: int, settings: dict):
```

并将函数内所有 `discount_threshold` 替换为 `effective_threshold`（在检测逻辑之后）。

- [ ] **Step 4: 修改 scan_portfolio_gen 的 signal_found step 增加 stock_price**

在 `signal_engine.py` 中已修复，确认 `scan_portfolio_gen` 第 100-111 行包含 `'stock_price': price`。

- [ ] **Step 5: 修改 signals.py 中对 scan_all_cb_gen 的调用，传入 settings**

在 `signals.py` 的 `event_generator` 函数中，找到：
```python
gen = scan_all_cb_gen(discount_threshold, target_lot_size)
```
改为：
```python
gen = scan_all_cb_gen(discount_threshold, target_lot_size, settings)
```

- [ ] **Step 6: Commit**

```bash
git add app/services/signal_engine.py app/routers/signals.py
git commit -m "feat: add profit calc funcs and naked arbitrage mode in scan_all_cb_gen"
```

---

## Task 4: trade_engine.py — settle_pending_trades 支持 NAKED 类型

**Files:**
- Modify: `app/services/trade_engine.py`

- [ ] **Step 1: 修改 settle_pending_trades 函数中的收益计算逻辑**

在 `for row in rows:` 循环内，检查 `row['trade_type']`。在 `sell_price = round(row['buy_price'] * 1.001, 2)` 计算之后，添加分支逻辑：

在 `sell_price = round(row['buy_price'] * 1.001, 2)` 之后、`sell_amount = sell_price * 100 * row['buy_shares']` 之前添加：

```python
            trade_type = row.get('trade_type', 'HEDGE')

            # 读取交易成本设置
            async with aiosqlite.connect(DB_PATH) as cost_db:
                cost_db.row_factory = aiosqlite.Row
                cost_cursor = await cost_db.execute("SELECT key, value FROM settings WHERE key IN ('stock_broker_fee','stock_stamp_tax','cb_broker_fee')")
                cost_rows = await cost_cursor.fetchall()
                cost_settings = {r['key']: float(r['value']) for r in cost_rows}
                stock_broker_fee = cost_settings.get('stock_broker_fee', 0.0001)
                stock_stamp_tax = cost_settings.get('stock_stamp_tax', 0.0015)
                cb_broker_fee = cost_settings.get('cb_broker_fee', 0.00006)

            if trade_type == 'NAKED':
                # 裸套：CB买入 → 转股 → 次日卖出正股
                conversion_price = row.get('conversion_price', 0)
                if conversion_price <= 0:
                    conversion_price = 100.0  # fallback
                net_profit, net_profit_rate = calc_net_profit_naked(
                    row['buy_price'], row['buy_shares'],
                    sell_price, conversion_price,
                    stock_broker_fee, cb_broker_fee
                )
                sell_amount = net_profit + row['buy_price'] * 100 * row['buy_shares'] + row['buy_price'] * 100 * row['buy_shares'] * cb_broker_fee
            else:
                # 持仓对冲：卖出正股覆盖成本
                net_profit, net_profit_rate = calc_net_profit_hedge(
                    row['buy_price'], row['buy_shares'], sell_price,
                    stock_broker_fee, stock_stamp_tax, cb_broker_fee
                )
                sell_amount = sell_price * 100 * row['buy_shares']
```

同时在 UPDATE 语句中，把 `'SETTLED'` 改为保持 status 不变（或新增一种 status）。实际上不需要改 status 逻辑，只需要在 profit 计算处区分。

注意：需要把 `calc_net_profit_hedge` 和 `calc_net_profit_naked` 从 `signal_engine.py` import 进来。

- [ ] **Step 2: 确认 settle_pending_trades 函数签名不需要改**

现有函数不需要改签名，成本参数在函数内部读取。

- [ ] **Step 3: Commit**

```bash
git add app/services/trade_engine.py
git commit -m "feat: settle_pending_trades calculates NAKED profit separately from HEDGE"
```

---

## Task 5: routers/settings.py — GET/PUT 透传新字段

**Files:**
- Modify: `app/routers/settings.py`

- [ ] **Step 1: 检查现有 GET 和 PUT 的返回值**

Read `app/routers/settings.py` 并确认 GET 返回的 dict 包含新增字段。

现有的 `get_scan_settings()` 返回：
```python
{
    "discount_threshold": float(s.get("discount_threshold", "-1.0")),
    "target_lot_size": int(s.get("target_lot_size", "10")),
    "scan_mode": s.get("scan_mode", "holdings"),
}
```

需要增加：
```python
    "stock_broker_fee": float(s.get("stock_broker_fee", "0.0001")),
    "stock_stamp_tax": float(s.get("stock_stamp_tax", "0.0015")),
    "cb_broker_fee": float(s.get("cb_broker_fee", "0.00006")),
    "naked_discount_threshold": float(s.get("naked_discount_threshold", "-2.0")),
    "naked_enabled": s.get("naked_enabled", "true") == "true",
```

- [ ] **Step 2: 检查 PUT 的字段处理**

确认 PUT 处理时能接受所有新字段。现有代码使用 `SettingsUpdate` 模型并直接执行 SQL `INSERT OR REPLACE`，会正确处理新增字段（只要 SettingsUpdate 模型包含它们）。

- [ ] **Step 3: Commit**

```bash
git add app/routers/settings.py
git commit -m "feat: settings API returns and accepts cost config and naked mode fields"
```

---

## Task 6: templates — settings.html 表单扩展 + index.html 结果区分

**Files:**
- Modify: `app/templates/settings.html`
- Modify: `app/templates/index.html`

- [ ] **Step 1: 在 settings.html 表单末尾，在 `<button type="submit">` 之前添加交易成本区块**

```html
        <div class="form-group">
            <label>股票券商佣金率</label>
            <input type="number" name="stock_broker_fee" id="stock_broker_fee"
                   step="0.0001" min="0" placeholder="默认 0.0001（万1）">
            <small style="color:#888;display:block;margin-top:4px;">
                买卖均收，默认万1（0.0001）
            </small>
        </div>

        <div class="form-group">
            <label>股票印花税率</label>
            <input type="number" name="stock_stamp_tax" id="stock_stamp_tax"
                   step="0.0001" min="0" placeholder="默认 0.0015（千1.5）">
            <small style="color:#888;display:block;margin-top:4px;">
                仅卖出时收取，默认千1.5（0.0015）
            </small>
        </div>

        <div class="form-group">
            <label>转债券商佣金率</label>
            <input type="number" name="cb_broker_fee" id="cb_broker_fee"
                   step="0.00001" min="0" placeholder="默认 0.00006（万0.6）">
            <small style="color:#888;display:block;margin-top:4px;">
                买卖均收，默认万0.6（0.00006）
            </small>
        </div>
```

- [ ] **Step 2: 在 settings.html 表单末尾，在 `</form>` 之前添加裸套模式区块**

```html
        <div class="form-group" style="margin-top: 20px; padding-top: 15px; border-top: 1px solid #eee;">
            <label>
                <input type="checkbox" name="naked_enabled" id="naked_enabled"
                       style="width: auto; margin-right: 8px;">
                启用裸套模式（底仓为空时）
            </label>
            <small style="color:#888;display:block;margin-top:4px;">
                开启后，当底仓为空时会使用裸套折价阈值扫描全市场转债（需更大的折价作为安全垫）
            </small>
        </div>

        <div class="form-group">
            <label>裸套折价阈值（%）</label>
            <input type="number" name="naked_discount_threshold" id="naked_discount_threshold"
                   step="0.1" placeholder="默认 -2.0">
            <small style="color:#888;display:block;margin-top:4px;">
                裸套模式只买溢价率低于此值的转债（如 -2.0 表示溢价率 < -2% 才触发）
            </small>
        </div>
```

- [ ] **Step 3: 修改 settings.html 的 loadSettings() 和 onsubmit 函数**

`loadSettings()` 中增加：
```javascript
document.getElementById('stock_broker_fee').value = s.stock_broker_fee;
document.getElementById('stock_stamp_tax').value = s.stock_stamp_tax;
document.getElementById('cb_broker_fee').value = s.cb_broker_fee;
document.getElementById('naked_discount_threshold').value = s.naked_discount_threshold;
document.getElementById('naked_enabled').checked = s.naked_enabled;
```

`onsubmit` 的 body 中增加：
```javascript
    const body = {
        discount_threshold: parseFloat(form.get('discount_threshold')),
        target_lot_size: parseInt(form.get('target_lot_size')),
        scan_mode: form.get('scan_mode'),
        stock_broker_fee: parseFloat(form.get('stock_broker_fee') || '0.0001'),
        stock_stamp_tax: parseFloat(form.get('stock_stamp_tax') || '0.0015'),
        cb_broker_fee: parseFloat(form.get('cb_broker_fee') || '0.00006'),
        naked_discount_threshold: parseFloat(form.get('naked_discount_threshold') || '-2.0'),
        naked_enabled: form.get('naked_enabled') === 'on',
    };
```

- [ ] **Step 4: 修改 index.html 的 done 事件处理，区分 trade_type**

在 `es.onerror = function()` 的 `if (finalResult)` 分支中，找到 `for (const t of finalResult.trades)` 循环。在 `<td>${t.cb_name} (${t.cb_code})</td>` 那一行之后，添加：

```javascript
                    const tradeTypeLabel = t.trade_type === 'NAKED' ? ' <span style="background:#f39c12;color:#fff;padding:1px 4px;border-radius:3px;font-size:11px;">裸套</span>' : '';
                    html += `<tr>
                        <td>${t.cb_name} (${t.cb_code})${tradeTypeLabel}</td>
```

- [ ] **Step 5: Commit**

```bash
git add app/templates/settings.html app/templates/index.html
git commit -m "feat: settings page adds cost config and naked mode form; index shows trade type badge"
```

---

## 自检清单

**Spec coverage:**
- [x] settings 5个新字段 → Task 1 + Task 2 + Task 5
- [x] trades trade_type 列 → Task 1
- [x] 收益计算函数 → Task 3
- [x] scan_all_cb_gen 裸套检测 → Task 3
- [x] settle NAKED → Task 4
- [x] settings.html 表单 → Task 6
- [x] index.html trade_type 显示 → Task 6

**Placeholder scan:** 无 TBD/TODO，所有步骤均有完整代码

**Type consistency:**
- `SettingsUpdate` 和 `SettingsResponse` 的字段名完全一致
- `calc_net_profit_hedge` 和 `calc_net_profit_naked` 签名匹配 `settle_pending_trades` 中的调用
- `scan_all_cb_gen(settings: dict)` 新签名在 `signals.py` 调用处同步更新
