# 可转债折溢价套利量化系统 - 设计文档

## 1. 项目概述

**项目名称**：CB-Arbitrage（可转债套利系统）

**核心功能**：每日尾盘扫描持仓正股对应的可转债，发现折价机会时自动执行模拟买入，次日开盘自动卖出，全量记录操作供回测分析。

**技术栈**：Python 3.10+ / FastAPI / SQLite / akshare / APScheduler

---

## 2. 系统架构

```
┌──────────────────────────────────────────────────────────┐
│                     Web 管理界面 (FastAPI)                 │
│  - 底仓管理（增删改查）                                     │
│  - 套利记录查询                                            │
│  - 持仓概览                                                │
│  - 每日信号推送记录                                         │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│              APScheduler 调度器                            │
│  - 每日 15:00 执行扫描 + 模拟买入                            │
│  - 每日 09:30 执行昨日持仓卖出                              │
│  - 支持手动触发单次扫描                                      │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                    数据层 (akshare)                        │
│  - 正股实时/历史价格                                        │
│  - 可转债行情（转债价格/转股价/溢价率/转股价值）              │
│  - 实时报价抓取                                            │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                   业务逻辑层                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  信号引擎     │  │ 模拟成交引擎 │  │   收益计算   │    │
│  │  折溢价计算   │  │ 买入/卖出    │  │  持仓成本    │    │
│  │  阈值判断    │  │ T+1转股记录  │  │  浮动盈亏    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                   SQLite 数据库                           │
└──────────────────────────────────────────────────────────┘
```

---

## 3. 数据库设计

### 3.1 表结构

#### holdings（用户底仓）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PRIMARY KEY | 自增ID |
| stock_code | TEXT NOT NULL | 正股代码（如 000001） |
| stock_name | TEXT NOT NULL | 正股名称 |
| shares | REAL NOT NULL | 持股数量 |
| cost_price | REAL NOT NULL | 成本价 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

#### scan_log（扫描日志）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PRIMARY KEY | 自增ID |
| scan_time | TIMESTAMP NOT NULL | 扫描时间 |
| target_stocks | TEXT | 本次扫描的正股列表（逗号分隔） |
| signals_found | INTEGER | 本次扫到的信号数量 |
| status | TEXT | SUCCESS/FAILED |

#### signals（套利信号）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PRIMARY KEY | 自增ID |
| scan_log_id | INTEGER | 关联扫描日志 |
| cb_code | TEXT NOT NULL | 可转债代码（如 113050） |
| cb_name | TEXT | 可转债名称 |
| stock_code | TEXT NOT NULL | 对应正股代码 |
| stock_price | REAL | 正股当前价 |
| cb_price | REAL | 转债当前价 |
| conversion_price | REAL | 转股价 |
| conversion_value | REAL | 转股价值 = (100/转股价)*正股价 |
| premium_rate | REAL | 溢价率(%) = (转债价/转股价值-1)*100 |
| discount_space | REAL | 折价空间 = 转股价值 - 转债价格 |
| target_buy_price | REAL | 目标买入价 |
| target_shares | INTEGER | 目标买入张数 |
| signal_time | TIMESTAMP | 信号产生时间 |
| status | TEXT | PENDING/EXECUTED/SKIPPED/EXPIRED |

#### trades（模拟成交记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PRIMARY KEY | 自增ID |
| signal_id | INTEGER | 关联信号 |
| cb_code | TEXT NOT NULL | 可转债代码 |
| cb_name | TEXT | 可转债名称 |
| buy_time | TIMESTAMP | 买入时间 |
| buy_price | REAL | 买入价格 |
| buy_shares | INTEGER | 买入张数（1张=100元） |
| buy_amount | REAL | 买入金额 = 买入价 * 100 * 张数 |
| sell_time | TIMESTAMP | 卖出时间 |
| sell_price | REAL | 卖出价格 |
| sell_amount | REAL | 卖出金额 |
| profit | REAL | 收益金额 = 卖出金额 - 买入金额 |
| profit_rate | REAL | 收益率(%) |
| status | TEXT | PENDING/SOLD/CANCELLED |

#### daily_summary（每日汇总）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PRIMARY KEY | 自增ID |
| trade_date | DATE UNIQUE | 交易日期 |
| total_signals | INTEGER | 当日信号数 |
| total_executed | INTEGER | 当日执行数 |
| total_profit | REAL | 当日总收益 |
| win_rate | REAL | 当日胜率 |
| created_at | TIMESTAMP | 创建时间 |

---

## 4. 核心业务逻辑

### 4.1 每日尾盘扫描（15:00）

```
1. 获取用户持仓正股列表（holdings表）
2. 对每只正股：
   a. 获取正股实时价格（akshare）
   b. 获取对应转债信息（转债代码/转债价格/转股价）
   c. 计算转股价值 = (100 / 转股价) * 正股价
   d. 计算溢价率 = (转债价格 / 转股价值 - 1) * 100
   e. 计算折价空间 = 转股价值 - 转债价格
3. 判断：溢价率 < -1%（即折价 > 1%）
4. 生成信号记录，状态置为 PENDING
5. 执行模拟买入：
   a. 目标买入张数 = 10张/手（固定）
   b. 买入价格 = 当前转债价格（模拟市价单）
   c. 记录买入时间/价格/数量
   d. 状态置为 PENDING
```

### 4.2 次日开盘卖出（09:30）

```
1. 查找所有状态为 PENDING 的持仓
2. 对每笔持仓：
   a. 获取转债当前/昨日收盘价
   b. 以开盘价模拟卖出
   c. 计算收益 = 卖出金额 - 买入金额
   d. 更新状态为 SOLD
3. 更新 daily_summary
```

### 4.3 信号优先级

当有多只转债同时满足条件时，按**折价空间从大到小**排序，优先操作折价最大的。

---

## 5. Web API 设计

### 5.1 底仓管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/holdings | 获取全部底仓 |
| POST | /api/holdings | 添加底仓 |
| PUT | /api/holdings/{id} | 更新底仓 |
| DELETE | /api/holdings/{id} | 删除底仓 |

**添加底仓请求体：**
```json
{
  "stock_code": "000001",
  "stock_name": "平安银行",
  "shares": 1000,
  "cost_price": 11.50
}
```

### 5.2 套利记录

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/signals | 查询信号记录（支持分页/日期过滤） |
| GET | /api/trades | 查询成交记录（支持分页/日期过滤） |
| GET | /api/daily-summary | 每日汇总查询 |

### 5.3 手动操作

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/scan | 手动触发一次扫描 |
| POST | /api/trades/{id}/cancel | 取消一笔待执行信号 |

### 5.4 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/overview | 总收益/胜率/持仓/信号统计 |

---

## 6. Web 界面设计

### 6.1 页面结构

```
/                首页 - 概览仪表盘
/holdings        底仓管理页面
/signals         信号记录页面
/trades          成交记录页面
/summary         每日汇总页面
```

### 6.2 首页概览

- 累计收益总额
- 累计胜率
- 当前持仓（可转债）
- 今日信号数
- 最近5条信号列表

### 6.3 底仓管理

- 表格展示底仓（正股代码/名称/数量/成本）
- 添加/编辑/删除按钮
- 支持手动刷新正股现价

### 6.4 信号记录

- 表格展示（转债代码/名称/折溢价率/信号时间/状态）
- 按日期范围筛选
- 显示关联的成交记录

### 6.5 成交记录

- 表格展示（买入时间/转债/买价/卖价/收益/收益率）
- 按日期范围筛选
- 支持导出CSV

---

## 7. 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| DISCOUNT_THRESHOLD | -1.0 | 折价率阈值（负值），超过此值触发信号 |
| TARGET_LOT_SIZE | 10 | 目标买入张数（固定10张=1手） |
| SCAN_TIME | "15:00" | 每日扫描时间 |
| SELL_TIME | "09:30" | 每日卖出时间 |
| DB_PATH | "./data/cb_arbitrage.db" | 数据库路径 |

---

## 8. 目录结构

```
E:\worksrc\lajimoney\
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置管理
│   ├── database.py          # SQLite 连接
│   ├── models.py            # Pydantic 模型
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── holdings.py      # 底仓 API
│   │   ├── signals.py        # 信号 API
│   │   ├── trades.py         # 成交 API
│   │   └── summary.py        # 汇总 API
│   ├── services/
│   │   ├── __init__.py
│   │   ├── data_fetcher.py   # akshare 数据获取
│   │   ├── signal_engine.py  # 信号计算引擎
│   │   ├── trade_engine.py   # 模拟成交引擎
│   │   └── scheduler.py      # 定时调度
│   └── templates/            # HTML 模板（可选：也可前后端分离）
├── data/                     # SQLite 数据库目录
├── tests/                   # 单元测试
├── docs/                    # 文档
├── requirements.txt
└── run.py                   # 启动脚本
```

---

## 9. 核心公式

**转股价值** = (100 / 转股价) × 正股现价

**溢价率** = (转债市价 / 转股价值 - 1) × 100%

**折价空间** = 转股价值 - 转债市价

**套利收益** = 卖出金额 - 买入金额

**收益率** = (套利收益 / 买入金额) × 100%

---

## 10. 已知限制与风险提示

1. **T+1 风险**：转债买入后 T+1 才能转股卖出，本系统简化为 T+1 日卖出（以开盘价模拟）
2. **流动性风险**：小盘转债冲击成本高，实盘需额外考虑
3. **数据延迟**：akshare 免费数据有延迟，不适合高频，实盘需切换付费源
4. **转股期限制**：未进入转股期的转债无法转股（系统未做此校验，模拟环境暂不处理）
5. **强赎风险**：触发强赎后价格可能暴跌（本系统未处理，模拟环境暂不处理）
