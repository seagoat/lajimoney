from fastapi import APIRouter, Query
from typing import Optional
import aiosqlite
from app.models import SignalResponse
from app.services.trade_engine import execute_scan_and_trade
from app.config import DB_PATH

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
