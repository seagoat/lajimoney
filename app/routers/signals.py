from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
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


async def load_holdings() -> dict[str, float]:
    """返回 {stock_code: shares}"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT stock_code, shares FROM holdings")
        return {r['stock_code']: r['shares'] for r in await cursor.fetchall()}


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


@router.delete("/{signal_id}")
async def delete_signal(signal_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM signals WHERE id = ?", (signal_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="信号不存在")
        await db.execute("DELETE FROM signals WHERE id = ?", (signal_id,))
        await db.commit()
        return {"message": "删除成功"}


@router.delete("")
async def delete_all_signals():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM signals")
        await db.commit()
        return {"message": f"已删除全部 {cursor.rowcount} 条信号记录"}


@router.post("/scan")
async def trigger_scan():
    """手动触发一次扫描+模拟买入（同步版本，立即返回结果）"""
    from app.services.trade_engine import execute_scan_and_trade
    result = await execute_scan_and_trade()
    return result


async def _run_scan(scan_id: str, settings: dict):
    """
    后台运行扫描，每步结果直接追加到 _scan_results[scan_id]['steps']
    """
    discount_threshold = float(settings["discount_threshold"])
    target_lot_size = int(settings["target_lot_size"])
    scan_mode = settings["scan_mode"]

    _scan_results[scan_id] = {"status": "running", "steps": [], "signals": [], "all_scanned": [], "done": False}

    try:
        if scan_mode == "all":
            gen = scan_all_cb_gen(discount_threshold, target_lot_size, settings)
        else:
            holdings_shares = await load_holdings()
            stock_codes = list(holdings_shares.keys())
            if not stock_codes:
                _scan_results[scan_id] = {
                    "status": "error",
                    "message": "底仓为空，请先添加正股或切换到全量扫描模式",
                    "done": True,
                }
                return
            gen = scan_portfolio_gen(stock_codes, discount_threshold, holdings_shares)

        signals = []

        try:
            async for step in gen:
                _scan_results[scan_id]["steps"].append(step)

                # 收集所有扫描到的CB（signal_found和not_qualified）
                if step['status'] in ('signal_found', 'not_qualified'):
                    all_scanned_item = {
                        'status': step['status'],
                        'cb_code': step['cb_code'],
                        'cb_name': step['cb_name'],
                        'stock_code': step['stock_code'],
                        'stock_name': step.get('stock_name'),
                        'stock_price': step.get('stock_price'),
                        'cb_price': step.get('cb_price'),
                        'conversion_price': step.get('conversion_price'),
                        'conversion_value': step.get('conversion_value'),
                        'premium_rate': step.get('premium_rate'),
                        'discount_space': step.get('discount_space'),
                        'has_holdings': step.get('has_holdings', False),
                    }
                    if step['status'] == 'signal_found':
                        all_scanned_item.update({
                            'target_buy_price': round(step['cb_price'], 2),
                            'target_shares': step.get('target_shares', target_lot_size),
                            'trade_type': step.get('trade_type', 'HEDGE'),
                            'short_available': step.get('short_available', False),
                        })
                        signals.append({
                            'cb_code': step['cb_code'],
                            'cb_name': step['cb_name'],
                            'stock_code': step['stock_code'],
                            'stock_name': step.get('stock_name'),
                            'stock_price': step['stock_price'],
                            'cb_price': step['cb_price'],
                            'conversion_price': step.get('conversion_price'),
                            'conversion_value': step.get('conversion_value'),
                            'premium_rate': step.get('premium_rate'),
                            'discount_space': step.get('discount_space'),
                            'target_buy_price': round(step['cb_price'], 2),
                            'target_shares': step.get('target_shares', target_lot_size),
                            'trade_type': step.get('trade_type', 'HEDGE'),
                            'short_available': step.get('short_available', False),
                        })
                    _scan_results[scan_id]["all_scanned"].append(all_scanned_item)
        except Exception as e:
            _scan_results[scan_id]["steps"].append({
                "event": "error",
                "message": f"扫描过程异常: {str(e)}",
            })

        # 只写入 signals 表，status 为 PENDING，不写 trades 表
        try:
            now = datetime.now().isoformat()
            async with aiosqlite.connect(DB_PATH) as db:
                target_stocks = scan_mode + "_mode"
                cursor = await db.execute(
                    "INSERT INTO scan_log (scan_time, target_stocks, signals_found, status) VALUES (?, ?, ?, ?)",
                    (now, target_stocks, len(signals), 'SUCCESS')
                )
                scan_log_id = cursor.lastrowid

                inserted = 0
                for sig in signals:
                    # 跳过已存在的相同机会（同一转债、相同买入价、相同张数视为重复）
                    cursor = await db.execute(
                        "SELECT id FROM signals WHERE cb_code = ? AND target_buy_price = ? AND target_shares = ? AND status = 'PENDING' LIMIT 1",
                        (sig['cb_code'], sig.get('target_buy_price'), sig.get('target_shares'))
                    )
                    if await cursor.fetchone():
                        continue
                    cursor = await db.execute(
                        """INSERT INTO signals
                        (scan_log_id, cb_code, cb_name, stock_code, stock_name, stock_price, cb_price,
                         conversion_price, conversion_value, premium_rate, discount_space,
                         target_buy_price, target_shares, trade_type, has_holdings, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
                        (scan_log_id, sig['cb_code'], sig['cb_name'], sig['stock_code'],
                         sig.get('stock_name'), sig['stock_price'], sig['cb_price'], sig['conversion_price'],
                         sig['conversion_value'], sig['premium_rate'], sig['discount_space'],
                         sig['target_buy_price'], sig['target_shares'],
                         sig.get('trade_type', 'HEDGE'), sig.get('has_holdings', False) and 1 or 0)
                    )
                    inserted += 1

                # 更新 scan_log 的实际信号数量
                await db.execute(
                    "UPDATE scan_log SET signals_found = ? WHERE id = ?",
                    (inserted, scan_log_id)
                )
                await db.commit()
        except Exception as e:
            _scan_results[scan_id]["steps"].append({
                "event": "error",
                "message": f"数据库写入异常: {str(e)}",
            })

        _scan_results[scan_id]["done"] = True
        _scan_results[scan_id]["status"] = "done"
        _scan_results[scan_id]["signals_found"] = inserted
        _scan_results[scan_id]["signals"] = signals
        _scan_results[scan_id]["message"] = (
            f"扫描完成，发现 {inserted} 个新信号" if inserted > 0 else "无符合条件信号"
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
        "scan_mode": s.get("scan_mode", "all"),
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
        asyncio.create_task(_run_scan(scan_id, settings))

        last_sent = 0

        for _ in range(120):
            await asyncio.sleep(1)
            result = _scan_results.get(scan_id)
            if not result:
                continue

            steps = result.get("steps", [])
            new_steps = steps[last_sent:]
            last_sent = len(steps)

            for step in new_steps:
                # 根据 step['status'] 决定 SSE 事件类型
                status = step.get('status', '')
                if status == 'skip' or status == 'not_qualified':
                    event_type = 'step'
                elif status == 'signal_found':
                    event_type = 'step'
                elif status == 'scanning':
                    event_type = 'start'  # 第一次 scanning = start 事件
                else:
                    event_type = 'step'

                data = {k: v for k, v in step.items() if k != 'event'}
                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                if event_type == 'error':
                    return

            if result.get("done"):
                yield f"event: done\ndata: {json.dumps({'signals_found': result.get('signals_found', 0), 'signals': result.get('signals', []), 'all_scanned': result.get('all_scanned', []), 'message': result.get('message', '')}, ensure_ascii=False)}\n\n"
                return

        yield f"event: done\ndata: {json.dumps({'signals_found': 0, 'signals': [], 'all_scanned': [], 'message': '扫描超时'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
