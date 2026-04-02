from fastapi import APIRouter, Query, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Optional
import aiosqlite
import json
from datetime import datetime
from app.models import SignalResponse
from app.config import DB_PATH
from app.services.signal_engine import scan_portfolio_gen, scan_all_cb_gen

router = APIRouter(prefix="/api/signals", tags=["信号管理"])

# 后台扫描状态存储
_scan_results: dict = {}


async def get_settings() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        return {r['key']: r['value'] for r in rows}


async def load_holdings() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT stock_code FROM holdings")
        return [r['stock_code'] for r in await cursor.fetchall()]


def log_msg(message, _type='info'):
    pass  # 日志已在前端处理


@router.get("", response_model=list[SignalResponse])
async def list_signals(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    stock_code: Optional[str] = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        where = []
        params = []
        if status:
            where.append("status = ?")
            params.append(status)
        if stock_code:
            where.append("stock_code = ?")
            params.append(stock_code)

        where_clause = ("WHERE " + " AND ".join(where)) if where else ""

        cursor = await db.execute(
            f"""SELECT * FROM signals {where_clause}
                ORDER BY signal_time DESC LIMIT ? OFFSET ?""",
            params + [limit, offset]
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


@router.post("/scan")
async def trigger_scan():
    """手动触发一次扫描+模拟买入（同步版本，立即返回结果）"""
    from app.services.trade_engine import execute_scan_and_trade
    result = await execute_scan_and_trade()
    return result


async def _run_scan(scan_id: str, settings: dict):
    """
    后台运行扫描，把进度和结果写入 _scan_results
    """
    discount_threshold = float(settings["discount_threshold"])
    target_lot_size = int(settings["target_lot_size"])
    scan_mode = settings["scan_mode"]

    _scan_results[scan_id] = {"status": "running", "steps": [], "signals": [], "done": False}

    try:
        if scan_mode == "all":
            gen = scan_all_cb_gen(discount_threshold, target_lot_size, settings)
        else:
            stock_codes = await load_holdings()
            if not stock_codes:
                _scan_results[scan_id] = {
                    "status": "error",
                    "message": "底仓为空，请先添加正股或切换到全量扫描模式",
                    "done": True,
                }
                return
            _scan_results[scan_id]["steps"].append({
                "event": "start",
                "status": "start",
                "total": len(stock_codes),
                "message": f"开始扫描 {len(stock_codes)} 只底仓正股...",
            })
            gen = scan_portfolio_gen(stock_codes, discount_threshold, target_lot_size)

        signals = []
        is_first = True

        try:
            async for step in gen:
                if is_first and step['status'] not in ('error',):
                    is_first = False
                    _scan_results[scan_id]["steps"].append({
                        "event": "start",
                        **{k: v for k, v in step.items() if k in ('total', 'message')},
                    })

                step_data = {"event": "step", **step}
                _scan_results[scan_id]["steps"].append(step_data)

                if step['status'] == 'signal_found':
                    if 'stock_price' not in step or 'cb_code' not in step:
                        continue
                    signals.append({
                        'cb_code': step['cb_code'],
                        'cb_name': step['cb_name'],
                        'stock_code': step['stock_code'],
                        'stock_price': step['stock_price'],
                        'cb_price': step['cb_price'],
                        'conversion_price': step.get('conversion_price'),
                        'conversion_value': step.get('conversion_value'),
                        'premium_rate': step.get('premium_rate'),
                        'discount_space': step.get('discount_space'),
                        'target_buy_price': round(step['cb_price'], 2),
                        'target_shares': target_lot_size,
                        'trade_type': step.get('trade_type', 'HEDGE'),
                    })
        except Exception as e:
            _scan_results[scan_id]["steps"].append({
                "event": "error",
                "message": f"扫描过程异常: {str(e)}",
            })

        # 写入数据库
        executed_trades = []
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
                        """ INSERT INTO signals
                        (scan_log_id, cb_code, cb_name, stock_code, stock_price, cb_price,
                         conversion_price, conversion_value, premium_rate, discount_space,
                         target_buy_price, target_shares, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
                        (scan_log_id, sig['cb_code'], sig['cb_name'], sig['stock_code'],
                         sig['stock_price'], sig['cb_price'], sig['conversion_price'],
                         sig['conversion_value'], sig['premium_rate'], sig['discount_space'],
                         sig['target_buy_price'], sig['target_shares'])
                    )
                    signal_id = cursor.lastrowid

                    buy_amount = sig['target_buy_price'] * 100 * sig['target_shares']
                    cursor = await db.execute(
                        """INSERT INTO trades
                        (signal_id, cb_code, cb_name, buy_time, buy_price, buy_shares, buy_amount, status, trade_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
                        (signal_id, sig['cb_code'], sig['cb_name'],
                         now, sig['target_buy_price'], sig['target_shares'], buy_amount,
                         sig.get('trade_type', 'HEDGE'))
                    )
                    trade_id = cursor.lastrowid
                    executed_trades.append({
                        'signal_id': signal_id,
                        'trade_id': trade_id,
                        **sig,
                        'buy_amount': buy_amount,
                    })

                    await db.execute(
                        "UPDATE signals SET status = 'EXECUTED' WHERE id = ?",
                        (signal_id,)
                    )

                await db.commit()
        except Exception as e:
            _scan_results[scan_id]["steps"].append({
                "event": "error",
                "message": f"数据库写入异常: {str(e)}",
            })

        _scan_results[scan_id]["done"] = True
        _scan_results[scan_id]["status"] = "done"
        _scan_results[scan_id]["signals_found"] = len(signals)
        _scan_results[scan_id]["trades"] = executed_trades
        _scan_results[scan_id]["message"] = (
            f"扫描完成，发现 {len(signals)} 个信号" if signals else "无符合条件信号"
        )

    except Exception as e:
        _scan_results[scan_id] = {
            "status": "error",
            "message": str(e),
            "done": True,
        }


@router.get("/settings")
async def get_scan_settings():
    """获取当前扫描设置"""
    s = await get_settings()
    return {
        "discount_threshold": float(s.get("discount_threshold", "-1.0")),
        "target_lot_size": int(s.get("target_lot_size", "10")),
        "scan_mode": s.get("scan_mode", "holdings"),
    }


@router.get("/scan-stream")
async def scan_stream():
    """
    SSE 流式扫描：后台运行，前端每秒轮询新步骤
    """
    scan_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    settings = await get_settings()

    async def event_generator():
        import asyncio
        # 启动后台扫描
        asyncio.create_task(_run_scan(scan_id, settings))

        last_sent = 0  # 已发送的 steps 计数

        for _ in range(120):
            await asyncio.sleep(1)
            result = _scan_results.get(scan_id)
            if not result:
                continue

            steps = result.get("steps", [])
            new_steps = steps[last_sent:]
            last_sent = len(steps)

            for step in new_steps:
                event_type = step.get('event', 'step')
                data = {k: v for k, v in step.items() if k != 'event'}
                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                if event_type == 'error':
                    return

            if result.get("done"):
                yield f"event: done\ndata: {json.dumps({'signals_found': result.get('signals_found', 0), 'trades': result.get('trades', []), 'message': result.get('message', '')}, ensure_ascii=False)}\n\n"
                return

        yield f"event: done\ndata: {json.dumps({'signals_found': 0, 'trades': [], 'message': '扫描超时'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
