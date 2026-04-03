# 融券对冲套利功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans

**Goal:** 新增 SHORT（融券对冲）套利模式，优先级：底仓对冲 > 融券对冲 > 裸套

**Architecture:** 在现有 HEDGE/NAKED 体系基础上，新增 SHORT 模式。新增 `loan_positions` 表记录融券负债，`margin_settings` 表存储券商保证金参数。收益计算新增含保证金占用成本和融券利息的公式。

**Tech Stack:** FastAPI + aiosqlite + Jinja2

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `app/database.py` | 新增 `loan_positions`、`margin_settings` 表；trades 表新增 `short_position_id` 列 |
| `app/models.py` | 新增 `MarginSettingsResponse`、`MarginSettingsUpdate`、`LoanPositionResponse` Pydantic 模型 |
| `app/services/margin_engine.py` | **新建**：融券利息计算 `calc_interest()`、保证金计算 `calc_margin_required()` |
| `app/services/signal_engine.py` | 新增 `calc_net_profit_short()`、修改 `scan_all_cb_gen()` 支持三种模式分支 |
| `app/services/trade_engine.py` | 修改 `settle_pending_trades()` 支持 SHORT 模式结算 |
| `app/routers/settings.py` | 新增 `GET/PUT /api/margin-settings` |
| `app/routers/margin.py` | **新建**：融券仓位 CRUD API |
| `app/templates/settings.html` | 新增券商保证金参数配置区块 |
| `app/templates/index.html` | 结果表格支持 SHORT 类型（蓝色标签）显示 |
| `app/templates/holdings.html` | 新增融券持仓区块显示 |
| `README.md` | 更新功能说明 |

---

## Task 1: 数据库迁移

**文件:** `app/database.py:88-121`（在现有迁移块之后追加新迁移）

**需修改的位置:** 紧接 `if 'trade_type' not in columns:` 迁移块之后

- [ ] **Step 1: 追加迁移代码**

在 `database.py` 的 `init_db()` 函数中，`for key, value in new_settings:` 之前追加：

```python
# 迁移：loan_positions 表
await db.execute("""
    CREATE TABLE IF NOT EXISTS loan_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id INTEGER NOT NULL,
        stock_code TEXT NOT NULL,
        stock_name TEXT,
        shares INTEGER NOT NULL,
        loan_price REAL NOT NULL,
        loan_amount REAL NOT NULL,
        loan_time TEXT NOT NULL,
        cover_time TEXT,
        cover_price REAL,
        cover_amount REAL,
        interest_days INTEGER DEFAULT 0,
        interest_rate REAL NOT NULL,
        interest_fee REAL DEFAULT 0,
        status TEXT DEFAULT 'ACTIVE',
        created_at TEXT,
        updated_at TEXT
    )
""")

# 迁移：margin_settings 表
await db.execute("""
    CREATE TABLE IF NOT EXISTS margin_settings (
        id INTEGER PRIMARY KEY,
        broker_name TEXT NOT NULL,
        margin_ratio REAL NOT NULL DEFAULT 0.5,
        daily_interest_rate REAL NOT NULL DEFAULT 0.00022,
        force_liquidation_ratio REAL NOT NULL DEFAULT 1.3,
        created_at TEXT,
        updated_at TEXT
    )
""")

# 迁移：trades 表新增 short_position_id 列
cursor = await db.execute("PRAGMA table_info(trades)")
existing_cols = [row[1] for row in await cursor.fetchall()]
if 'short_position_id' not in existing_cols:
    await db.execute("ALTER TABLE trades ADD COLUMN short_position_id INTEGER")

# 迁移：trades 表新增 conversion_price 列（NAKED/SHORT 结算需要）
if 'conversion_price' not in existing_cols:
    await db.execute("ALTER TABLE trades ADD COLUMN conversion_price REAL")

# 插入默认券商配置（如果不存在）
cursor = await db.execute("SELECT id FROM margin_settings LIMIT 1")
if not await cursor.fetchone():
    now = datetime.now().isoformat()
    await db.execute(
        """INSERT INTO margin_settings
           (id, broker_name, margin_ratio, daily_interest_rate, force_liquidation_ratio, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (1, '默认券商', 0.5, 0.00022, 1.3, now, now)
    )
```

---

## Task 2: Pydantic 模型

**文件:** `app/models.py`（在文件末尾追加）

- [ ] **Step 1: 新增模型**

```python
# === 融券设置模型 ===

class MarginSettingsResponse(BaseModel):
    id: int
    broker_name: str
    margin_ratio: float          # 保证金比例
    daily_interest_rate: float   # 日利率
    force_liquidation_ratio: float


class MarginSettingsUpdate(BaseModel):
    broker_name: Optional[str] = None
    margin_ratio: Optional[float] = None
    daily_interest_rate: Optional[float] = None
    force_liquidation_ratio: Optional[float] = None


# === 融券仓位模型 ===

class LoanPositionResponse(BaseModel):
    id: int
    trade_id: int
    stock_code: str
    stock_name: Optional[str]
    shares: int
    loan_price: float
    loan_amount: float
    loan_time: str
    cover_time: Optional[str]
    cover_price: Optional[float]
    cover_amount: Optional[float]
    interest_days: int
    interest_rate: float
    interest_fee: float
    status: str  # ACTIVE / COVERED
    created_at: str
    updated_at: str
```

同时给 `SettingsResponse` 和 `SettingsUpdate` 新增字段：
- `SettingsResponse` 新增 `short_enabled: bool`
- `SettingsUpdate` 新增 `short_enabled: Optional[bool] = None`

---

## Task 3: margin_engine.py

**文件:** `app/services/margin_engine.py`（新建）

- [ ] **Step 1: 写入利息和保证金计算函数**

```python
"""
融券保证金与利息计算引擎
"""

def calc_interest(loan_amount: float, daily_rate: float, days: int) -> float:
    """
    计算融券利息
    loan_amount: 融券卖出总额
    daily_rate: 日利率（小数，如 0.00022）
    days: 计息天数
    """
    return round(loan_amount * daily_rate * days, 2)


def calc_margin_required(loan_amount: float, margin_ratio: float) -> float:
    """
    计算所需保证金
    loan_amount: 融券卖出总额
    margin_ratio: 保证金比例（小数，如 0.5）
    """
    return loan_amount * margin_ratio


def calc_net_profit_short(
    loan_price: float,
    shares: int,
    cb_buy_price: float,
    cb_shares: int,
    cover_price: float,
    conversion_price: float,
    daily_interest_rate: float,
    interest_days: int,
    stock_broker_fee: float,
    cb_broker_fee: float,
    margin_ratio: float
) -> tuple[float, float]:
    """
    SHORT 模式净收益计算
    融券卖出正股 + 买CB + 转股归还 + 利息

    Returns: (net_profit, net_profit_rate_percent)
    """
    # 融券卖出所得
    loan_amount = loan_price * shares

    # CB买入成本（含佣金）
    cb_buy_amount = cb_buy_price * 100 * cb_shares
    cb_buy_commission = cb_buy_amount * cb_broker_fee
    total_cb_cost = cb_buy_amount + cb_buy_commission

    # 转股获得股数
    shares_from_cb = (100.0 / conversion_price) * cb_shares if conversion_price > 0 else 0

    # 归还买入成本（买股还券）
    cover_amount = cover_price * shares_from_cb
    cover_commission = cover_amount * stock_broker_fee
    total_cover_cost = cover_amount + cover_commission

    # 融券卖出佣金
    loan_commission = loan_amount * stock_broker_fee

    # 融券利息
    interest = calc_interest(loan_amount, daily_interest_rate, interest_days)

    # 净收益 = 卖券所得 - 买CB成本 - 归还成本 - 利息 - 佣金
    net_profit = loan_amount - total_cb_cost - total_cover_cost - interest - loan_commission - cover_commission

    # 保证金占用作为分母计算收益率
    margin_required = calc_margin_required(cb_buy_amount, margin_ratio)
    net_profit_rate = round(net_profit / margin_required * 100, 4) if margin_required > 0 else 0.0

    return round(net_profit, 2), net_profit_rate
```

- [ ] **Step 2: 验证文件可正常导入**

Run: `E:/worksrc/lajimoney/.venv/Scripts/python.exe -c "from app.services.margin_engine import calc_net_profit_short, calc_interest; print('OK')"`
Expected: OK（无输出则成功）

---

## Task 4: SHORT 模式信号计算

**文件:** `app/services/signal_engine.py`（在末尾追加 `calc_net_profit_short` 调用）

**修改位置 1:** `calc_net_profit_naked` 函数定义处之后（追加 `calc_net_profit_short` 导入引用）

**修改位置 2:** `scan_all_cb_gen()` 函数中的融券判断分支

- [ ] **Step 1: 在 `signal_engine.py` 末尾追加 SHORT 模式收益计算函数引用**

在文件末尾（`calc_net_profit_naked` 之后）追加：

```python
def calc_net_profit_short(
    loan_price: float,
    shares: int,
    cb_buy_price: float,
    cb_shares: int,
    cover_price: float,
    conversion_price: float,
    daily_interest_rate: float,
    interest_days: int,
    stock_broker_fee: float,
    cb_broker_fee: float,
    margin_ratio: float
) -> tuple[float, float]:
    """
    SHORT 模式净收益计算
    融券卖出正股 + 买CB + 转股归还
    """
    loan_amount = loan_price * shares
    cb_buy_amount = cb_buy_price * 100 * cb_shares
    cb_buy_commission = cb_buy_amount * cb_broker_fee
    total_cb_cost = cb_buy_amount + cb_buy_commission

    shares_from_cb = (100.0 / conversion_price) * cb_shares if conversion_price > 0 else 0
    cover_amount = cover_price * shares_from_cb
    cover_commission = cover_amount * stock_broker_fee
    loan_commission = loan_amount * stock_broker_fee
    interest = loan_amount * daily_interest_rate * interest_days

    net_profit = loan_amount - total_cb_cost - cover_amount - interest - loan_commission - cover_commission
    margin_required = cb_buy_amount * margin_ratio
    net_profit_rate = round(net_profit / margin_required * 100, 4) if margin_required > 0 else 0.0
    return round(net_profit, 2), net_profit_rate
```

- [ ] **Step 2: 修改 `scan_all_cb_gen()` 函数中的模式判断逻辑**

找到以下代码（在 `scan_all_cb_gen` 函数内部）：
```python
trade_type = 'NAKED' if is_naked else 'HEDGE'
```

替换为：
```python
# 判断执行模式：底仓 > 融券 > 裸套
if is_naked:
    if naked_enabled:
        trade_type = 'SHORT'  # 启用融券模式
    else:
        trade_type = 'NAKED'  # 裸套兜底
else:
    trade_type = 'HEDGE'  # 有底仓
```

同时在 signal_found 的 yield 中加入 `trade_type` 字段：
```python
'trade_type': trade_type,
```

---

## Task 5: trade_engine.py SHORT 结算

**文件:** `app/services/trade_engine.py:97-179`（修改 `settle_pending_trades()` 函数）

- [ ] **Step 1: 修改 `settle_pending_trades()` 支持 SHORT 模式**

在 `trade_engine.py` 顶部 import 区追加：
```python
from app.services.margin_engine import calc_net_profit_short
```

找到 `settle_pending_trades()` 中这段代码：
```python
if trade_type == 'NAKED':
    ...
else:
    # 持仓对冲
```

替换为：
```python
if trade_type == 'NAKED':
    # 裸套：CB买入 → 转股 → 次日卖出正股
    ...
elif trade_type == 'SHORT':
    # 融券对冲：融券卖出 → CB买入转股 → 归还融券
    conversion_price = row.get('conversion_price') or 100.0
    if conversion_price <= 0:
        conversion_price = 100.0

    # 获取融券仓位信息
    short_pos_id = row.get('short_position_id')
    loan_cursor = await db.execute(
        "SELECT * FROM loan_positions WHERE id = ?",
        (short_pos_id,) if short_pos_id else (0,)
    )
    loan_row = await loan_cursor.fetchone()
    if loan_row:
        loan_price = loan_row['loan_price']
        shares_from_loan = loan_row['shares']
        daily_interest_rate = loan_row['interest_rate']
        interest_days = loan_row['interest_days']
        margin_ratio = float(settings.get('margin_ratio', '0.5'))
    else:
        loan_price = row.get('stock_price', row['buy_price'])
        shares_from_loan = row['buy_shares']
        daily_interest_rate = 0.00022
        interest_days = 1
        margin_ratio = 0.5

    net_profit, net_profit_rate = calc_net_profit_short(
        loan_price=loan_price,
        shares=shares_from_loan,
        cb_buy_price=row['buy_price'],
        cb_shares=row['buy_shares'],
        cover_price=sell_price,  # 用模拟的次日开盘价
        conversion_price=conversion_price,
        daily_interest_rate=daily_interest_rate,
        interest_days=interest_days,
        stock_broker_fee=stock_broker_fee,
        cb_broker_fee=cb_broker_fee,
        margin_ratio=margin_ratio
    )
    profit = net_profit
    profit_rate = net_profit_rate

    # 平掉融券仓位
    if loan_row and short_pos_id:
        from datetime import datetime as dt
        now_str = dt.now().isoformat()
        await db.execute(
            """UPDATE loan_positions SET
            status = 'COVERED', cover_time = ?, cover_price = ?,
            cover_amount = ?, interest_fee = ?, interest_days = ?,
            updated_at = ?
            WHERE id = ?""",
            (now_str, sell_price, round(sell_price * shares_from_loan, 2),
             round(loan_row['loan_amount'] * daily_interest_rate * interest_days, 2),
             interest_days, now_str, short_pos_id)
        )
else:
    # 持仓对冲
    ...
```

同时在 `if trade_type == 'NAKED':` 分支中补充 `conversion_price` 的获取：
```python
conversion_price = row.get('conversion_price') or 100.0
```

---

## Task 6: margin_settings API

**文件:** `app/routers/settings.py`（在文件末尾追加 margin settings 端点）

**同时新建:** `app/routers/margin.py`（融券仓位 CRUD）

- [ ] **Step 1: 修改 settings.py，在文件末尾追加**

```python
@router.get("/margin-settings")
async def get_margin_settings():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM margin_settings LIMIT 1")
        row = await cursor.fetchone()
        if not row:
            return {"id": None, "broker_name": "", "margin_ratio": 0.5,
                    "daily_interest_rate": 0.00022, "force_liquidation_ratio": 1.3}
        return dict(zip([d[0] for d in cursor.description], row))


@router.put("/margin-settings")
async def update_margin_settings(settings: MarginSettingsUpdate):
    async with aiosqlite.connect(DB_PATH) as db:
        from datetime import datetime
        now = datetime.now().isoformat()
        updates = []
        values = []
        if settings.broker_name is not None:
            updates.append("broker_name = ?")
            values.append(settings.broker_name)
        if settings.margin_ratio is not None:
            updates.append("margin_ratio = ?")
            values.append(settings.margin_ratio)
        if settings.daily_interest_rate is not None:
            updates.append("daily_interest_rate = ?")
            values.append(settings.daily_interest_rate)
        if settings.force_liquidation_ratio is not None:
            updates.append("force_liquidation_ratio = ?")
            values.append(settings.force_liquidation_ratio)
        updates.append("updated_at = ?")
        values.append(now)
        await db.execute(
            f"UPDATE margin_settings SET {', '.join(updates)} WHERE id = 1",
            values
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM margin_settings WHERE id = 1")
        row = await cursor.fetchone()
        return dict(zip([d[0] for d in cursor.description], row))
```

在 `settings.py` 顶部 import 区追加 `MarginSettingsUpdate` 的导入：
```python
from app.models import ..., MarginSettingsUpdate
```

- [ ] **Step 2: 新建 app/routers/margin.py**

```python
from fastapi import APIRouter, HTTPException
from datetime import datetime
import aiosqlite
from app.config import DB_PATH
from app.models import LoanPositionResponse

router = APIRouter(prefix="/api/margin", tags=["融券管理"])


@router.get("/positions", response_model=list[LoanPositionResponse])
async def list_loan_positions(status: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = "WHERE status = ?" if status else ""
        params = [status] if status else []
        cursor = await db.execute(
            f"SELECT * FROM loan_positions {where} ORDER BY created_at DESC",
            params
        )
        rows = await cursor.fetchall()
        return [dict(zip([d[0] for d in cursor.description], r)) for r in rows]


@router.delete("/{position_id}")
async def close_loan_position(position_id: int):
    """手动平仓融券仓位（模拟归还）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM loan_positions WHERE id = ?", (position_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="融券仓位不存在")
        if row['status'] == 'COVERED':
            raise HTTPException(status_code=400, detail="该仓位已平仓")

        now = datetime.now().isoformat()
        cover_price = round(row['loan_price'] * 0.999, 2)  # 模拟归还时股价略低
        cover_amount = round(cover_price * row['shares'], 2)
        interest_fee = round(row['loan_amount'] * row['interest_rate'] * row['interest_days'], 2)

        await db.execute(
            """UPDATE loan_positions SET
            status = 'COVERED', cover_time = ?, cover_price = ?,
            cover_amount = ?, interest_fee = ?, updated_at = ?
            WHERE id = ?""",
            (now, cover_price, cover_amount, interest_fee, now, position_id)
        )
        await db.commit()
        return {"message": "平仓成功", "cover_price": cover_price, "interest_fee": interest_fee}
```

---

## Task 7: signals.py 新增 SHORT 执行逻辑

**文件:** `app/routers/signals.py`（修改 `_run_scan()` 函数中 signals 保存部分）

- [ ] **Step 1: 在 `_run_scan()` 的 signals 保存循环中，新增 SHORT 模式的融券记录写入**

在 `signals.py` 中找到插入 `trades` 表的代码块，在 `cursor = await db.execute("INSERT INTO trades ...` 之后，`await db.commit()` 之前，追加：

```python
# 如果是 SHORT 模式，写入融券仓位记录
if sig.get('trade_type') == 'SHORT':
    loan_shares = sig.get('shares_from_cb', 0)  # 转股获得的股数，即融券卖出的股数
    loan_price = sig.get('stock_price', 0)
    loan_amount = round(loan_price * loan_shares, 2)
    daily_interest = float(settings.get('margin_daily_interest', '0.00022'))

    cursor = await db.execute(
        """INSERT INTO loan_positions
        (trade_id, stock_code, stock_name, shares, loan_price, loan_amount,
         loan_time, interest_rate, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)""",
        (trade_id, sig['stock_code'], sig.get('stock_name', ''),
         loan_shares, loan_price, loan_amount,
         now, daily_interest, now, now)
    )
    loan_position_id = cursor.lastrowid

    # 更新 trades 表的 short_position_id
    await db.execute(
        "UPDATE trades SET short_position_id = ? WHERE id = ?",
        (loan_position_id, trade_id)
    )
```

同时在 `from app.models import SignalResponse` 附近追加导入：
```python
from app.services.margin_engine import calc_net_profit_short
```

---

## Task 8: 前端模板更新

### settings.html

- [ ] **Step 1: 在设置页面追加券商保证金配置区块**

在现有表单之后追加：

```html
<div class="card">
    <h2>券商保证金设置</h2>
    <form id="marginSettingsForm">
        <div class="form-group">
            <label>券商名称</label>
            <input type="text" id="broker_name" placeholder="如 国信证券">
        </div>
        <div class="form-group">
            <label>保证金比例</label>
            <input type="number" id="margin_ratio" step="0.01" min="0.1" max="1.0">
            <small>如 0.5 表示50%保证金</small>
        </div>
        <div class="form-group">
            <label>日利率</label>
            <input type="number" id="daily_interest_rate" step="0.00001">
            <small>年化约8%时为 0.00022</small>
        </div>
        <div class="form-group">
            <label>强制平仓维持率</label>
            <input type="number" id="force_liquidation_ratio" step="0.01">
            <small>如 1.3 表示保证金低于130%时强平</small>
        </div>
        <div class="form-group">
            <label>启用融券模式</label>
            <input type="checkbox" id="short_enabled">
        </div>
        <button type="submit" class="btn btn-primary">保存</button>
    </form>
</div>
```

同时在 `<script>` 中追加：

```javascript
async function loadMarginSettings() {
    const res = await fetch('/api/settings/margin-settings');
    if (!res.ok) return;
    const s = await res.json();
    document.getElementById('broker_name').value = s.broker_name || '';
    document.getElementById('margin_ratio').value = s.margin_ratio || 0.5;
    document.getElementById('daily_interest_rate').value = s.daily_interest_rate || 0.00022;
    document.getElementById('force_liquidation_ratio').value = s.force_liquidation_ratio || 1.3;
}

document.getElementById('marginSettingsForm').onsubmit = async (e) => {
    e.preventDefault();
    const body = {
        broker_name: document.getElementById('broker_name').value,
        margin_ratio: parseFloat(document.getElementById('margin_ratio').value),
        daily_interest_rate: parseFloat(document.getElementById('daily_interest_rate').value),
        force_liquidation_ratio: parseFloat(document.getElementById('force_liquidation_ratio').value),
    };
    await fetch('/api/settings/margin-settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
    });
    alert('保存成功');
    loadMarginSettings();
};

loadMarginSettings();
```

### index.html

- [ ] **Step 2: 修改扫描结果表格中的 trade_type 显示**

在 `done` 事件处理中，找到类型标签生成逻辑：

```javascript
const tradeTypeLabel = t.trade_type === 'NAKED'
    ? '<span style="background:#f39c12;color:#fff;padding:1px 4px;border-radius:3px;font-size:11px;">裸套</span>'
    : '<span style="background:#27ae60;color:#fff;padding:1px 4px;border-radius:3px;font-size:11px;">对冲</span>';
```

替换为：

```javascript
const tradeTypeLabel = t.trade_type === 'NAKED'
    ? '<span style="background:#f39c12;color:#fff;padding:1px 4px;border-radius:3px;font-size:11px;">裸套</span>'
    : t.trade_type === 'SHORT'
    ? '<span style="background:#3498db;color:#fff;padding:1px 4px;border-radius:3px;font-size:11px;">融券</span>'
    : '<span style="background:#27ae60;color:#fff;padding:1px 4px;border-radius:3px;font-size:11px;">对冲</span>';
```

### holdings.html

- [ ] **Step 3: 新增融券持仓区块**

在"当前底仓"表格下方追加：

```html
<div class="card" style="margin-top: 20px;">
    <h2>融券持仓</h2>
    <table>
        <thead>
            <tr>
                <th>股票代码</th>
                <th>名称</th>
                <th>融券数量</th>
                <th>融券价格</th>
                <th>融券总额</th>
                <th>利息</th>
                <th>状态</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody id="loanPositionsBody">
            <tr><td colspan="8">加载中...</td></tr>
        </tbody>
    </table>
</div>
```

在 `<script>` 中追加：

```javascript
async function loadLoanPositions() {
    const res = await fetch('/api/margin/positions');
    const data = await res.json();
    const tbody = document.getElementById('loanPositionsBody');
    if (data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8">暂无融券持仓</td></tr>';
        return;
    }
    tbody.innerHTML = data.map(p => `
        <tr>
            <td>${p.stock_code}</td>
            <td>${p.stock_name || '-'}</td>
            <td>${p.shares}</td>
            <td>${p.loan_price}</td>
            <td>${p.loan_amount.toFixed(2)}</td>
            <td>${p.interest_fee > 0 ? p.interest_fee.toFixed(2) : '-'}</td>
            <td class="${p.status === 'ACTIVE' ? 'loss' : 'profit'}">${p.status === 'ACTIVE' ? '持仓中' : '已平仓'}</td>
            <td>
                ${p.status === 'ACTIVE' ? `<button class="btn btn-danger btn-sm" onclick="closePosition(${p.id})">平仓</button>` : '-'}
            </td>
        </tr>
    `).join('');
}

async function closePosition(id) {
    if (!confirm('确认平仓？')) return;
    await fetch(`/api/margin/${id}`, { method: 'DELETE' });
    loadLoanPositions();
}

loadLoanPositions();
```

---

## Task 9: README.md 更新

- [ ] **Step 1: 在 README.md 中补充融券对冲模式说明**

在"裸套模式（NAKED）"章节之后追加：

```markdown
### 融券对冲模式（SHORT）

用户没有正股底仓，但券商支持融券时的套利方式：

1. 全市场扫描：寻找折价较大的转债（溢价率 < 裸套阈值）
2. 判断：无底仓但可融券
3. 融券卖出正股（做空）→ 获得现金
4. 买入转债 + 立即转股
5. T+1日：用转股获得的正股归还融券
6. 剩余现金 - 融券利息 = 净收益

**关键参数：**
- 保证金比例（默认50%）
- 日利率（默认0.022%，年化约8%）
- 强制平仓线（默认130%）

**风险提示：**
- 融券利息按日计息，持有越久成本越高
- 本系统为模拟系统，实际操作以券商规则为准
```

同时更新"核心参数说明"表格，新增一行 `short_enabled`。

---

## 自查清单

- [ ] spec 中所有功能都有对应 Task 覆盖
- [ ] 无任何 TODO/TBD 占位符
- [ ] 函数签名在所有引用处一致
- `calc_net_profit_short` 的参数顺序：loan_price, shares, cb_buy_price, cb_shares, cover_price, conversion_price, daily_interest_rate, interest_days, stock_broker_fee, cb_broker_fee, margin_ratio
- `trade_type` 枚举值：`'HEDGE'` | `'NAKED'` | `'SHORT'`
- 数据库列名：`short_position_id`、`conversion_price`、`loan_positions`、`margin_settings`
