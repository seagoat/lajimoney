from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from typing import Optional
import aiosqlite
import json
from datetime import datetime
from app.models import SignalResponse
from app.services.trade_engine import execute_scan_and_trade
from app.services.signal_engine import scan_portfolio_gen
from app.config import DB_PATH, TARGET_LOT_SIZE

router = APIRouter(prefix="/api/signals", tags=["信号管理"])


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
    """手动触发一次扫描+模拟买入"""
    result = await execute_scan_and_trade()
    return result


@router.get("/scan-stream")
async def scan_stream():
    """
    流式扫描接口，通过 SSE 实时推送每只正股的扫描状态
    """
    async def event_generator():
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT stock_code FROM holdings")
            rows = await cursor.fetchall()
            stock_codes = [r['stock_code'] for r in rows]

        if not stock_codes:
            yield f"event: error\ndata: {json.dumps({'message': '底仓为空，请先添加正股'})}\n\n"
            return

        # 先推送开始状态
        yield f"event: start\ndata: {json.dumps({'total': len(stock_codes), 'message': f'开始扫描 {len(stock_codes)} 只正股...'})}\n\n"

        signals = []
        async for step in scan_portfolio_gen(stock_codes):
            yield f"event: step\ndata: {json.dumps(step, ensure_ascii=False)}\n\n"

            if step['status'] == 'signal_found':
                signals.append({
                    'cb_code': step['cb_code'],
                    'cb_name': step['cb_name'],
                    'stock_code': step['stock_code'],
                    'stock_price': step['stock_price'],
                    'cb_price': step['cb_price'],
                    'conversion_price': step['conversion_price'],
                    'conversion_value': step['conversion_value'],
                    'premium_rate': step['premium_rate'],
                    'discount_space': step['discount_space'],
                    'target_buy_price': round(step['cb_price'], 2),
                    'target_shares': TARGET_LOT_SIZE,
                })

        # 写入数据库
        now = datetime.now().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "INSERT INTO scan_log (scan_time, target_stocks, signals_found, status) VALUES (?, ?, ?, ?)",
                (now, ','.join(stock_codes), len(signals), 'SUCCESS')
            )
            scan_log_id = cursor.lastrowid

            executed_trades = []
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
                signal_id = cursor.lastrowid

                buy_amount = sig['target_buy_price'] * 100 * sig['target_shares']
                cursor = await db.execute(
                    """INSERT INTO trades
                    (signal_id, cb_code, cb_name, buy_time, buy_price, buy_shares, buy_amount, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
                    (signal_id, sig['cb_code'], sig['cb_name'],
                     now, sig['target_buy_price'], sig['target_shares'], buy_amount)
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

        # 推送完成状态
        result = {
            'signals_found': len(signals),
            'trades': executed_trades,
            'message': f'扫描完成，发现 {len(signals)} 个信号' if signals else '无符合条件信号',
        }
        yield f"event: done\ndata: {json.dumps(result, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
