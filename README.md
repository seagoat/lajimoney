# 可转债折溢价套利系统

可转债折溢价套利量化模拟系统，支持持仓对冲模式和全市场裸套模式。

## 系统要求

- Python 3.10+
- Windows / macOS / Linux
- 网络连接（数据请求）

## 快速启动

### Windows

```batch
.\run.bat
```

### macOS / Linux

```bash
./run.sh
```

浏览器访问：http://localhost:8001

## 功能说明

### 底仓管理
在"底仓管理"页面添加你持有的正股代码和持仓数量

### 手动扫描
首页点击"手动触发扫描"：
- **持仓模式**：扫描底仓正股对应的可转债
- **全市场模式**：扫描全市场可转债（耗时约 20-60 秒）

### 扫描逻辑
- 折价阈值：溢价率低于设定值时触发买入信号
- 每次买入：固定张数（可配置）
- 裸套模式：底仓为空时，可开启全市场扫描寻找大折价转债

### 成交记录与结算
- 系统自动记录模拟买入
- 支持手动结算：按次日模拟开盘价计算收益
- 收益含交易成本（佣金、印花税）

### 交易成本配置
可在"扫描设置"页面配置：
- 股票券商佣金率（默认万1）
- 股票印花税率（默认千1.5，仅卖出）
- 转债券商佣金率（默认万0.6）

## 核心参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 折价阈值 | -1.0% | 溢价率低于此值触发信号 |
| 每次买入 | 10张 | 每手=10张 |
| 扫描模式 | 仅持仓正股 | 或全市场转债 |
| 裸套折价阈值 | -2.0% | 裸套模式专用，更严格 |
| 股票佣金 | 万1 | 买卖均收 |
| 印花税 | 千1.5 | 仅卖出时收取 |
| 转债佣金 | 万0.6 | 买卖均收 |

## 技术架构

- **后端**：FastAPI + SQLite (aiosqlite)
- **前端**：Jinja2 模板 + 原生 JavaScript
- **数据源**：新浪财经（实时价格）+ THS 同花顺（转债基础信息）
- **环境管理**：uv（自动安装，如未检测到）

## 项目结构

```
app/
  main.py           # FastAPI 入口
  database.py       # SQLite 初始化与迁移
  models.py         # Pydantic 数据模型
  config.py         # 数据库路径配置
  routers/          # API 路由
    holdings.py     # 底仓管理 API
    signals.py      # 信号与扫描 API
    trades.py       # 成交记录 API
    summary.py      # 汇总统计 API
    settings.py     # 设置 API
  services/
    data_fetcher.py    # 新浪+THS 数据获取
    signal_engine.py    # 信号计算引擎
    trade_engine.py     # 模拟成交执行
  templates/        # Jinja2 HTML 模板
    base.html
    index.html
    holdings.html
    signals.html
    trades.html
    settings.html
run.py              # uvicorn 启动脚本
run.bat             # Windows 启动脚本
requirements.txt     # Python 依赖
```
