# 融券对冲套利功能设计

## 背景

现有系统支持两种 CB 套利模式：
- **HEDGE（持仓对冲）**：用户持有正股底仓，买入折价 CB，转股后卖出底仓，锁定价差
- **NAKED（裸套）**：无底仓，买入 CB，T+1 转股后次日卖出正股，承担隔夜风险

本次新增：
- **SHORT（融券对冲）**：无底仓但可融券，融券卖出正股 + 买入 CB 转股归还，对冲隔夜风险

## 操作流程

### SHORT 模式（T+1 简化模拟）

```
T 日
  1. 扫描全市场，发现某 CB 折价
  2. 判断：无底仓 + 可融券
  3. 融券卖出正股（做空）→ 获得现金
  4. 买入 CB（付出现金）
  5. 申请转股

T+1 日
  6. 转股到账，获得正股
  7. 使用正股归还融券（平空头）
  8. 剩余现金 - 融券利息 = 净收益
```

**核心约束**：若 T+1 日转股到账前正股大涨，融券卖出方有逼空风险（裸套同样的 T+1 问题）。融券对冲通过提前锁定卖出价格，将风险转移给市场。

---

## 优先级判断逻辑

```
扫到信号 → 有底仓?
              ├─ 有 → HEDGE
              └─ 无 → 可融券?
                        ├─ 是 → SHORT
                        └─ 否 → 折价 >= NAKED 阈值?
                                  ├─ 是 → NAKED
                                  └─ 否 → 无操作
```

---

## 数据库设计

### 新增表：loan_positions（融券负债记录）

```sql
CREATE TABLE loan_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,           -- 对应的成交记录ID
    stock_code TEXT NOT NULL,            -- 融券股票代码
    stock_name TEXT,
    shares INTEGER NOT NULL,             -- 融券数量（股数）
    loan_price REAL NOT NULL,           -- 融券卖出价格
    loan_amount REAL NOT NULL,           -- 融券卖出总额 = loan_price * shares
    loan_time TEXT NOT NULL,             -- 融券时间
    cover_time TEXT,                     -- 归还时间（平仓后填写）
    cover_price REAL,                    -- 归还买入价格
    cover_amount REAL,                   -- 归还买入总额
    interest_days INTEGER DEFAULT 0,    -- 计息天数
    interest_rate REAL NOT NULL,        -- 日利率（小数，如 0.00022）
    interest_fee REAL DEFAULT 0,         -- 利息总额
    status TEXT DEFAULT 'ACTIVE',        -- ACTIVE / COVERED
    created_at TEXT,
    updated_at TEXT
);
```

### 新增表：margin_settings（券商保证金配置）

```sql
CREATE TABLE margin_settings (
    id INTEGER PRIMARY KEY,
    broker_name TEXT NOT NULL,           -- 券商名称，如"国信证券"
    margin_ratio REAL NOT NULL DEFAULT 0.5,   -- 保证金比例（默认50%）
    daily_interest_rate REAL NOT NULL DEFAULT 0.00022, -- 日利率（默认年化8%）
    force_liquidation_ratio REAL NOT NULL DEFAULT 1.3, -- 维持保证金低于此比例强制平仓
    created_at TEXT,
    updated_at TEXT
);
```

### 修改表：trades

新增字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| short_position_id | INTEGER | 关联的 loan_positions.id（仅 SHORT 模式） |

### 修改表：holdings

无需修改。底仓（普通持仓）和融券负债严格分开管理。

---

## 收益率计算公式

### SHORT 模式净收益

```
融券卖出所得  = loan_price × shares
CB买入成本    = cb_price × 100 × cb_shares
转股获得股数  = 100 ÷ conversion_price × cb_shares
归还所需股数  = 转股获得股数
归还买入成本  = cover_price × 归还股数
融券利息      = loan_amount × daily_interest_rate × days_held
券商佣金(卖)  = loan_amount × stock_broker_fee
券商佣金(买)  = cover_amount × stock_broker_fee + cb_buy_amount × cb_broker_fee

净收益 = 融券卖出所得 - CB买入成本 - 归还买入成本 - 融券利息 - 所有佣金
收益率 = 净收益 ÷ (CB买入成本 × 保证金比例) × 100%
```

---

## 设置页面新增参数

| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| broker_name | 券商设置 | 空 | 券商名称 |
| margin_ratio | 券商设置 | 50% | 保证金比例 |
| daily_interest_rate | 券商设置 | 0.022%/日 | 日利率 |
| force_liquidation_ratio | 券商设置 | 130% | 维持保证金低于此比例强平 |
| short_enabled | 扫描设置 | false | 是否启用融券模式 |

---

## 券商选择与费率查询

### 券商配置
- 用户在设置页面选择/输入券商名称（如"国信证券"）
- 费率信息默认使用上表默认值
- 用户可手动修改各参数

### 可融券判断逻辑
通过交易所公开的融资融券标的证券名单判断（聚宽/Tushare 公开接口）：
- 若股票在交易所公布的融资融券池内 → 标记为"可融券"
- 券商会动态调整，实际是否有券仍需用户确认
- 系统仅提供参考，不作为实际可融券保证

---

## 界面设计

### 首页扫描监控
扫描完成后，结果表格新增"类型"列，显示：
- `对冲`：绿色标签，有底仓
- `融券`：蓝色标签，无底仓但可融券
- `裸套`：橙色标签，无底仓无融券，仅展示

### 底仓管理页面
分两块显示：
1. **普通持仓**（现有表格）
2. **融券持仓**（新增 tab 或折叠区）
   - 显示：股票代码、名称、融券数量、融券价格、利息、状态

### 成交记录页面
SHORT 模式的记录：
- 显示融券卖出价、融券利息、归还价
- 收益率单独计算（含保证金占用成本）

---

## 技术架构

### 新增文件

| 文件 | 职责 |
|------|------|
| `app/routers/margin.py` | 融券设置、融券仓位查询 API |
| `app/services/margin_engine.py` | 融券利息计算、保证金计算 |
| `app/services/loan_engine.py` | 融券对冲执行逻辑 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `app/database.py` | 新增 loan_positions、margin_settings 表 |
| `app/models.py` | 新增 Pydantic 模型 |
| `app/services/signal_engine.py` | 新增 SHORT 模式判断和计算逻辑 |
| `app/services/trade_engine.py` | 新增 SHORT 模式成交和结算 |
| `app/routers/signals.py` | 新增 SHORT 模式执行分支 |
| `app/routers/holdings.py` | 新增融券仓位查询 |
| `app/routers/settings.py` | 新增 margin_settings API |
| `app/templates/index.html` | 结果表格支持 SHORT 类型显示 |
| `app/templates/holdings.html` | 新增融券持仓 tab |
| `app/templates/settings.html` | 新增券商保证金参数配置 |
| `README.md` | 更新功能说明 |

---

## 风险说明（用户提示）

SHORT 模式界面需明确展示：
- 融券利息按日计息，持有越久成本越高
- 若转股延迟或券商无法借券，操作可能失败
- 保证金低于维持率时可能被动平仓
- 本系统为模拟系统，实际操作以券商规则为准
