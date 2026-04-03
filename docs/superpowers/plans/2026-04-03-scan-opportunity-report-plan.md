# 扫描机会报告改造 - 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将扫描功能从"模拟买入"改为"机会报告"模式，展示预估成本/收益/风险/操作步骤；同时将所有页面表格改为可点击表头排序。

**Architecture:** 扫描结果仅写入 signals 表(PENDING)，不写 trades 表。前端在 SSE 完成后根据三种策略计算预估成本/收益/风险等级/操作步骤，用统一表格展示。排序功能在前端 JS 实现。

**Tech Stack:** FastAPI + Jinja2 templates + vanilla JS (无前端框架)，SSE 流式扫描

---

## 文件改动总览

| 文件 | 改动内容 |
|------|---------|
| `app/models.py` | `SettingsUpdate`/`SettingsResponse` 新增 `short_max_fund`, `naked_max_fund` |
| `app/routers/settings.py` | 新增两个字段的读写 |
| `app/routers/signals.py` | `_run_scan()` 停止写入 trades；移除 SHORT 模式 loan_positions 写入；扫描参数从 settings 表读取新字段 |
| `app/services/signal_engine.py` | `scan_all_cb_gen()` 中 SHORT/NAKED 目标张数按资金上限计算；HEDGE 保持不变 |
| `app/templates/settings.html` | 新增"融券最大资金"和"裸套最大资金"两个输入框 |
| `app/templates/index.html` | 扫描结果从"模拟买入表格"改为"机会报告表格"；增加前端排序 JS |
| `app/templates/signals.html` | 增加前端表头排序 |
| `app/templates/trades.html` | 增加前端表头排序 |
| `app/templates/holdings.html` | 增加前端表头排序 |

---

## Task 1: 数据模型更新

**Files:**
- Modify: `app/models.py:89-111`

- [ ] **Step 1: 修改 SettingsResponse**

在 `SettingsResponse` 类（大约第90行）中添加两个字段：

```python
class SettingsResponse(BaseModel):
    # ... 现有字段 ...
    short_max_fund: float  # 融券模式单次最大资金（元）
    naked_max_fund: float  # 裸套模式单次最大资金（元）
```

- [ ] **Step 2: 修改 SettingsUpdate**

在 `SettingsUpdate` 类中添加两个字段：

```python
class SettingsUpdate(BaseModel):
    # ... 现有字段 ...
    short_max_fund: Optional[float] = None
    naked_max_fund: Optional[float] = None
```

---

## Task 2: Settings API 支持新字段

**Files:**
- Modify: `app/routers/settings.py:10-82`

- [ ] **Step 1: 修改 get_settings() 返回值**

在 `GET /api/settings` 的返回字典中（大约第17行 return 之前）添加：
```python
"short_max_fund": float(settings.get("short_max_fund", "100000")),
"naked_max_fund": float(settings.get("naked_max_fund", "100000")),
```

- [ ] **Step 2: 修改 update_settings() 写入逻辑**

在 `PUT /api/settings` 的 `await db.commit()` 之前添加：
```python
if update.short_max_fund is not None:
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
        ("short_max_fund", str(update.short_max_fund), now)
    )
if update.naked_max_fund is not None:
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
        ("naked_max_fund", str(update.naked_max_fund), now)
    )
```

---

## Task 3: Settings 页面新增两个配置项

**Files:**
- Modify: `app/templates/settings.html:1-213`

- [ ] **Step 1: 在现有表单中新增两个输入框**

在"无底仓套利模式"卡片中的 `<div class="form-group">` 内（在 `<div class="card" style="margin-top: 20px;">` 之后、"无底仓套利模式"内容之前）添加：

```html
<div class="card" style="margin-top: 20px;">
    <h2>套利资金上限</h2>
    <div class="form-group">
        <label>融券模式单次最大资金（元）</label>
        <input type="number" name="short_max_fund" id="short_max_fund"
               step="1000" min="0" placeholder="默认 100000">
        <small style="color:#888;display:block;margin-top:4px;">
            融券对冲模式下，单次操作投入的最大资金量，默认10万元
        </small>
    </div>

    <div class="form-group">
        <label>裸套模式单次最大资金（元）</label>
        <input type="number" name="naked_max_fund" id="naked_max_fund"
               step="1000" min="0" placeholder="默认 100000">
        <small style="color:#888;display:block;margin-top:4px;">
            裸套模式下，单次操作投入的最大资金量，默认10万元
        </small>
    </div>
</div>
```

- [ ] **Step 2: 修改 loadSettings() 加载逻辑**

在 `loadSettings()` 函数中（大约第155行附近），在已有的 `document.getElementById(...)` 赋值语句之后添加：
```javascript
document.getElementById('short_max_fund').value = s.short_max_fund || 100000;
document.getElementById('naked_max_fund').value = s.naked_max_fund || 100000;
```

- [ ] **Step 3: 修改表单提交数据**

在 `settingsForm.onsubmit` 的 `body` 对象中（在 `short_enabled` 之后）添加：
```javascript
short_max_fund: parseFloat(form.get('short_max_fund') || '100000'),
naked_max_fund: parseFloat(form.get('naked_max_fund') || '100000'),
```

---

## Task 4: Signal Engine 目标张数重写

**Files:**
- Modify: `app/services/signal_engine.py:188-314`

- [ ] **Step 1: 在 scan_all_cb_gen() 中读取新设置参数**

在 `_run_scan()` 调用 `scan_all_cb_gen()` 之前（大约第106行），`settings` 字典已包含所有设置。确保在 `scan_all_cb_gen()` 内部，从 `settings` 参数读取：
```python
short_max_fund = float(settings.get("short_max_fund", "100000"))
naked_max_fund = float(settings.get("naked_max_fund", "100000"))
```

- [ ] **Step 2: 重写 SHORT 模式目标张数计算**

在 `scan_all_cb_gen()` 中，找到 `trade_type == 'SHORT'` 的 `signal_found` yield 处（大约第279-298行）。在 yield 字典中修改 `target_shares` 的计算逻辑：

替换原有的 `target_shares: target_lot_size` 为：
```python
# SHORT 模式：按融券资金上限计算
# 可买入CB张数 = floor(融券资金上限 / (CB价格 * 100))，向下取整
short_max_fund = float(settings.get("short_max_fund", "100000"))
target_shares_calc = int(short_max_fund / (cb_price * 100))
target_shares_calc = max(target_shares_calc // 10 * 10, 10)  # 至少10张，向下取整到10的倍数
```

> 注意：由于 scan_all_cb_gen 是异步生成器，settings 参数已经传入，直接用 `settings.get()` 即可。

- [ ] **Step 3: 重写 NAKED 模式目标张数计算**

在 `trade_type == 'NAKED'` 的 yield 处（大约第272-274行附近），同样替换 `target_shares`：

```python
# NAKED 模式：按裸套资金上限计算
naked_max_fund = float(settings.get("naked_max_fund", "100000"))
target_shares_calc = int(naked_max_fund / (cb_price * 100))
target_shares_calc = max(target_shares_calc // 10 * 10, 10)  # 至少10张
```

- [ ] **Step 4: 确保 HEDGE 模式不变**

HEDGE 模式（有底仓）的 `target_shares` 计算保持不变（按底仓股数换算），已在现有代码中实现。

---

## Task 5: Signals Router 移除交易写入逻辑

**Files:**
- Modify: `app/routers/signals.py:1-353`

- [ ] **Step 1: 修改 _run_scan() 中对 settings 的读取**

在 `_run_scan()` 函数开头（大约第94-102行），从 settings 字典读取新字段：
```python
discount_threshold = float(settings["discount_threshold"])
target_lot_size = int(settings["target_lot_size"])
scan_mode = settings["scan_mode"]
short_max_fund = float(settings.get("short_max_fund", "100000"))
naked_max_fund = float(settings.get("naked_max_fund", "100000"))
```

将 `settings` 参数传递给 `scan_all_cb_gen()` 调用（如果尚未传递）：
```python
gen = scan_all_cb_gen(discount_threshold, target_lot_size, settings)
```

- [ ] **Step 2: 移除 trades 写入逻辑**

在 `_run_scan()` 函数中，找到 `executed_trades = []` 开始的大段代码（大约第150-262行）。**删除**以下内容：
- `executed_trades` 列表的构建
- `cursor = await db.execute("INSERT INTO trades ...", ...)` 及相关所有代码
- SHORT 模式的 `loan_positions` 写入代码
- `await db.execute("UPDATE signals SET status = 'EXECUTED' WHERE id = ?", ...)`
- `executed_trades` 相关的所有内容

替换为：扫描完成后直接将 `signals` 写入数据库（status 保持 `PENDING`），不写 trades：
```python
signals = []
try:
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        target_stocks = scan_mode + "_mode"
        cursor = await db.execute(
            "INSERT INTO scan_log (scan_time, target_stocks, signals_found, status) VALUES (?, ?, ?, ?)",
            (now, target_stocks, len(signals), 'SUCCESS')
        )
        scan_log_id = cursor.lastrowid

        for sig in signals:
            cursor = await db.execute(
                """INSERT INTO signals
                (scan_log_id, cb_code, cb_name, stock_code, stock_price, cb_price,
                 conversion_price, conversion_value, premium_rate, discount_space,
                 target_buy_price, target_shares, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
                (scan_log_id, sig['cb_code'], sig['cb_name'], sig['stock_code'],
                 sig['stock_price'], sig['cb_price'], sig['conversion_price'],
                 sig['conversion_value'], sig['premium_rate'], sig['discount_space'],
                 sig['target_buy_price'], sig['target_shares'])
            )
        await db.commit()
except Exception as e:
    _scan_results[scan_id]["steps"].append({
        "event": "error",
        "message": f"数据库写入异常: {str(e)}",
    })
```

- [ ] **Step 3: 修改 SSE done 事件中的返回数据**

在 SSE `done` 事件的数据中（大约第340行），将：
```python
'trades': executed_trades
```
改为：
```python
'signals': signals  # 不再返回 trades
```

- [ ] **Step 4: 修改 signals router GET /scan-stream 传递 settings**

在 `scan_stream()` 函数中（大约第297行），`settings` 已通过 `await get_settings()` 获取并传递给 `_run_scan()`，无需额外改动（因为 `_run_scan` 使用的是 settings 字典）。

---

## Task 6: Index 页面机会报告表格

**Files:**
- Modify: `app/templates/index.html:1-201`

- [ ] **Step 1: 添加排序 JS 函数**

在 `<script>` 块的最前面（`let currentEventSource = null;` 之前）添加通用的表头排序函数：

```javascript
// 表格排序功能
let sortState = {};  // {tableId: {column: 'colName', direction: 'asc'|'desc'}}

function makeSortable(tableId) {
    const headers = document.querySelectorAll(`#${tableId} th[data-sort]`);
    headers.forEach(th => {
        th.style.cursor = 'pointer';
        th.title = '点击排序';
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            const current = sortState[tableId];
            if (current && current.column === col) {
                current.direction = current.direction === 'asc' ? 'desc' : 'asc';
            } else {
                sortState[tableId] = { column: col, direction: 'asc' };
            }
            sortTable(tableId, col, sortState[tableId].direction);
        });
        // 添加排序指示器
        if (!th.querySelector('.sort-indicator')) {
            th.innerHTML += ' <span class="sort-indicator" style="font-size:10px;color:#ccc;"></span>';
        }
    });
}

function sortTable(tableId, col, direction) {
    const tbody = document.querySelector(`#${tableId} tbody`);
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const colIndex = Array.from(document.querySelectorAll(`#${tableId} th[data-sort]`)).findIndex(th => th.dataset.sort === col);
    
    rows.sort((a, b) => {
        let aVal = a.cells[colIndex]?.textContent.trim() || '';
        let bVal = b.cells[colIndex]?.textContent.trim() || '';
        // 尝试转为数字
        const aNum = parseFloat(aVal.replace(/[^\d.-]/g, ''));
        const bNum = parseFloat(bVal.replace(/[^\d.-]/g, ''));
        if (!isNaN(aNum) && !isNaN(bNum)) {
            return direction === 'asc' ? aNum - bNum : bNum - aNum;
        }
        return direction === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    });
    
    rows.forEach(row => tbody.appendChild(row));
    
    // 更新排序指示器
    document.querySelectorAll(`#${tableId} th .sort-indicator`).forEach(el => el.textContent = '');
    const activeHeader = document.querySelector(`#${tableId} th[data-sort="${col}"] .sort-indicator`);
    if (activeHeader) activeHeader.textContent = direction === 'asc' ? ' ▲' : ' ▼';
}
```

- [ ] **Step 2: 修改 done 事件处理函数中的表格渲染逻辑**

在 `es.addEventListener('done', function(e) {...})` 中（大约第146行），找到 `resultDiv2.innerHTML = html;` 的位置。

将原有的模拟买入表格 HTML 替换为机会报告表格：

```javascript
if (finalResult.signals_found > 0) {
    let html = `<p class="profit"><strong>扫描完成，发现 ${finalResult.signals_found} 个套利机会：</strong></p>`;
    html += `<table id="opportunityTable" style="margin-top:10px;width:100%;border-collapse:collapse;">
        <thead>
            <tr>
                <th data-sort="cb">转债</th>
                <th data-sort="stock">正股</th>
                <th data-sort="strategy">策略</th>
                <th data-sort="premium">溢价率</th>
                <th data-sort="discount">折价空间</th>
                <th data-sort="buyPrice">目标买入价</th>
                <th data-sort="shares">目标张数</th>
                <th data-sort="cost">预估成本(元)</th>
                <th data-sort="profit">预估收益(元)</th>
                <th data-sort="profitRate">预估收益率</th>
                <th data-sort="risk">风险等级</th>
                <th data-sort="steps">操作步骤</th>
            </tr>
        </thead>
        <tbody id="opportunityTableBody">
        </tbody>
    </table>`;
    resultDiv2.innerHTML = html;

    // 计算并填充每行数据
    const tbody = document.getElementById('opportunityTableBody');
    for (const sig of finalResult.signals) {
        // 计算预估成本、收益、收益率
        const buyPrice = sig.target_buy_price || sig.cb_price;
        const cbAmount = buyPrice * 100 * sig.target_shares;
        const sharesFromCb = (100.0 / sig.conversion_price) * sig.target_shares;

        let cost = 0, profit = 0, riskLevel = '', steps = '', strategyLabel = '';
        const stockPrice = sig.stock_price || 0;
        const strategy = sig.trade_type || 'HEDGE';

        if (strategy === 'HEDGE') {
            const cbFee = cbAmount * 0.00006 * 2;
            const stockSellAmount = cbAmount;
            const stockFee = stockSellAmount * 0.0001;
            const stampTax = stockSellAmount * 0.0015;
            cost = cbAmount + cbFee + stockFee + stampTax;
            profit = stockSellAmount - cost;
            riskLevel = '<span style="color:#27ae60;">低</span>';
            steps = '买入CB → 转股 → 卖出正股';
            strategyLabel = '<span style="background:#27ae60;color:#fff;padding:1px 4px;border-radius:3px;font-size:11px;">对冲</span>';
        } else if (strategy === 'SHORT') {
            const cbFee = cbAmount * 0.00006;
            const loanSellAmount = stockPrice * sharesFromCb;
            const loanFee = loanSellAmount * 0.0001;
            const interest = loanSellAmount * 0.00022 * 1;
            cost = cbAmount + cbFee + loanFee + interest;
            profit = loanSellAmount - cost;
            riskLevel = '<span style="color:#27ae60;">低</span>';
            steps = '买入CB → 申请融券卖出正股 → 转股归还融券';
            strategyLabel = '<span style="background:#3498db;color:#fff;padding:1px 4px;border-radius:3px;font-size:11px;">融券</span>';
        } else {
            const cbFee = cbAmount * 0.00006;
            const stockSellAmount = stockPrice * sharesFromCb;
            const stockFee = stockSellAmount * 0.0001;
            cost = cbAmount + cbFee + stockFee;
            profit = stockSellAmount - cost;
            riskLevel = '<span style="color:#e74c3c;">高</span>';
            steps = '买入CB → 转股 → 次日卖出正股（注意隔夜风险）';
            strategyLabel = '<span style="background:#f39c12;color:#fff;padding:1px 4px;border-radius:3px;font-size:11px;">裸套</span>';
        }

        const profitRate = cbAmount > 0 ? (profit / cbAmount * 100).toFixed(2) + '%' : '-';
        const premium = sig.premium_rate != null ? sig.premium_rate.toFixed(2) + '%' : '-';
        const discount = sig.discount_space != null ? sig.discount_space.toFixed(2) : '-';
        const cbInfo = sig.cb_name ? `${sig.cb_name} (${sig.cb_code})` : sig.cb_code;
        const stockInfo = sig.stock_name ? `${sig.stock_name} (${sig.stock_code})` : sig.stock_code;
        const riskForSort = strategy === 'HEDGE' ? 'low' : strategy === 'SHORT' ? 'low' : 'high';

        tbody.innerHTML += `<tr>
            <td>${cbInfo}</td>
            <td>${stockInfo}</td>
            <td>${strategyLabel}</td>
            <td class="${sig.premium_rate < 0 ? 'profit' : 'loss'}">${premium}</td>
            <td>${discount}</td>
            <td>${buyPrice.toFixed(2)}</td>
            <td>${sig.target_shares}</td>
            <td>${cost.toFixed(2)}</td>
            <td class="${profit >= 0 ? 'profit' : 'loss'}">${profit.toFixed(2)}</td>
            <td class="${profit >= 0 ? 'profit' : 'loss'}">${profitRate}</td>
            <td data-risk="${riskForSort}">${riskLevel}</td>
            <td style="font-size:12px;">${steps}</td>
        </tr>`;
    }

    // 绑定排序功能
    makeSortable('opportunityTable');
} else {
    resultDiv2.innerHTML = '<p>扫描完成，今日无符合条件信号（折价率需 &lt; ' + (finalResult.settings?.discount_threshold || -1) + '%）</p>';
}
```

- [ ] **Step 3: 修改 done 事件数据来源**

在发送 done 事件前（大约第339行），将：
```python
'trades': executed_trades
```
改为：
```python
'signals': signals,
'settings': {
    'discount_threshold': discount_threshold,
    'short_max_fund': short_max_fund,
    'naked_max_fund': naked_max_fund,
    'stock_broker_fee': float(settings.get('stock_broker_fee', '0.0001')),
    'stock_stamp_tax': float(settings.get('stock_stamp_tax', '0.0015')),
    'cb_broker_fee': float(settings.get('cb_broker_fee', '0.00006')),
    'margin_daily_interest': float(settings.get('margin_daily_interest', '0.00022')),
}
```

同时在 `_scan_results[scan_id]` 初始化处确保 `signals` 列表正确收集（参考 Task 5 Step 2 的 signals 收集逻辑）。

- [ ] **Step 4: 更新 SSE done 事件解析**

在前端 `es.addEventListener('done', ...)` 的回调中（大约第146行），将 `finalResult.trades` 相关代码移除，因为不再有 trades 数据。

---

## Task 7: Signals 页面表头排序

**Files:**
- Modify: `app/templates/signals.html:1-75`

- [ ] **Step 1: 添加排序 JS 函数**

在 `<script>` 块开头（`async function loadSignals()` 之前）添加：

```javascript
let sortState = { signalsTable: { column: 'signal_time', direction: 'desc' } };

function makeSortable(tableId, defaultCol, defaultDir) {
    sortState[tableId] = { column: defaultCol, direction: defaultDir };
    const headers = document.querySelectorAll(`#${tableId} th[data-sort]`);
    headers.forEach(th => {
        th.style.cursor = 'pointer';
        th.title = '点击排序';
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if (sortState[tableId].column === col) {
                sortState[tableId].direction = sortState[tableId].direction === 'asc' ? 'desc' : 'asc';
            } else {
                sortState[tableId] = { column: col, direction: 'asc' };
            }
            sortTable(tableId, col, sortState[tableId].direction);
        });
        if (!th.querySelector('.sort-indicator')) {
            th.innerHTML += ' <span class="sort-indicator" style="font-size:10px;color:#ccc;"></span>';
        }
    });
    // 设置默认排序列的指示器
    const defaultHeader = document.querySelector(`#${tableId} th[data-sort="${defaultCol}"] .sort-indicator`);
    if (defaultHeader) defaultHeader.textContent = defaultDir === 'asc' ? ' ▲' : ' ▼';
}

function sortTable(tableId, col, direction) {
    const tbody = document.querySelector(`#${tableId} tbody`);
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const colIndex = Array.from(document.querySelectorAll(`#${tableId} th[data-sort]`)).findIndex(th => th.dataset.sort === col);

    rows.sort((a, b) => {
        let aVal = a.cells[colIndex]?.textContent.trim() || '';
        let bVal = b.cells[colIndex]?.textContent.trim() || '';
        const aNum = parseFloat(aVal.replace(/[^\d.-]/g, ''));
        const bNum = parseFloat(bVal.replace(/[^\d.-]/g, ''));
        if (!isNaN(aNum) && !isNaN(bNum)) {
            return direction === 'asc' ? aNum - bNum : bNum - aNum;
        }
        return direction === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    });

    rows.forEach(row => tbody.appendChild(row));
    document.querySelectorAll(`#${tableId} th .sort-indicator`).forEach(el => el.textContent = '');
    const activeHeader = document.querySelector(`#${tableId} th[data-sort="${col}"] .sort-indicator`);
    if (activeHeader) activeHeader.textContent = direction === 'asc' ? ' ▲' : ' ▼';
}
```

- [ ] **Step 2: 给 table 的 thead th 添加 data-sort 属性**

在 `<thead>` 中的 `<tr>` 内，将每个 `<th>` 添加 `data-sort` 属性：

```html
<th data-sort="signal_time">时间</th>
<th data-sort="cb_code">转债代码</th>
<th data-sort="cb_name">转债名称</th>
<th data-sort="stock_code">正股代码</th>
<th data-sort="premium_rate">溢价率</th>
<th data-sort="discount_space">折价空间</th>
<th data-sort="target_buy_price">目标买入价</th>
<th data-sort="target_shares">张数</th>
<th data-sort="status">状态</th>
<th>操作</th>
```

- [ ] **Step 3: 在 loadSignals() 末尾调用 makeSortable()**

在 `loadSignals()` 函数的最后添加：
```javascript
makeSortable('signalsTable', 'signal_time', 'desc');
```

注意：`status` 列因为不是 `data-sort` 所以不参与排序。

---

## Task 8: Trades 页面表头排序

**Files:**
- Modify: `app/templates/trades.html`

- [ ] **Step 1: 查看 trades.html 当前结构**

使用 Read 工具读取 `app/templates/trades.html`，了解其结构。

- [ ] **Step 2: 应用与 Signals 页面相同的排序模式**

参照 Task 7 的实现，为 trades.html 添加相同的排序 JS 函数和 `data-sort` 属性。主要改动：

- `<th>` 添加 `data-sort` 属性（如 `data-sort="buy_time"`, `data-sort="profit"`, `data-sort="profit_rate"` 等）
- `<script>` 开头添加排序 JS 代码
- `loadTrades()` 末尾调用 `makeSortable('tradesTable', 'buy_time', 'desc')`

---

## Task 9: Holdings 页面表头排序

**Files:**
- Modify: `app/templates/holdings.html`

- [ ] **Step 1: 查看 holdings.html 当前结构**

使用 Read 工具读取 `app/templates/holdings.html`。

- [ ] **Step 2: 应用与 Signals 页面相同的排序模式**

参照 Task 7 的实现，为 holdings.html 添加相同的排序 JS 函数和 `data-sort` 属性。

---

## Task 10: 数据库 settings 表默认值

**Files:**
- Modify: `app/database.py` 或通过代码注入

- [ ] **Step 1: 检查 database.py 中的 settings 初始化**

读取 `app/database.py`，找到 `settings` 表的初始化 SQL（或 seed 数据）。

- [ ] **Step 2: 添加新字段的默认值**

在 settings 表的初始数据中（或迁移逻辑中），确保 `short_max_fund` 和 `naked_max_fund` 有默认值 "100000"。如果使用 `INSERT OR IGNORE INTO settings` 模式，需确保这两个 key 在初始化时被写入。

---

## 验证清单

- [ ] Settings 页面可以保存并加载"融券最大资金"和"裸套最大资金"
- [ ] 全市场扫描时，SHORT/NAKED 模式的目标张数按各自资金上限计算
- [ ] 扫描完成后 signals 表写入 PENDING 状态，不写 trades 表
- [ ] 首页机会报告表格显示预估成本/收益/收益率/风险等级/操作步骤
- [ ] Signals/Trades/Holdings 页面表格点击表头可排序
- [ ] 排序有视觉指示器（▲/▼）
- [ ] 已退市转债（vol=0 或转股价=NaN）不再出现在扫描结果中
