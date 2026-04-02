from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import aiosqlite
from app.models import TradeResponse
from app.config import DB_PATH

router = APIRouter(prefix="/api/trades", tags=["成交记录"])


@router.get("", response_model=list[TradeResponse])
async def list_trades(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        where = []
        params = []
        if status:
            where.append("status = ?")
            params.append(status)

        where_clause = ("WHERE " + " AND ".join(where)) if where else ""

        cursor = await db.execute(
            f"""SELECT * FROM trades {where_clause}
                ORDER BY buy_time DESC LIMIT ? OFFSET ?""",
            params + [limit, offset]
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


@router.post("/{trade_id}/settle")
async def settle_trade(trade_id: int):
    """手动结算一笔持仓（模拟卖出）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="成交记录不存在")
        if row['status'] != 'PENDING':
            raise HTTPException(status_code=400, detail="只能结算PENDING状态的持仓")

        # 模拟卖出
        sell_price = round(row['buy_price'] * 1.001, 2)
        sell_amount = sell_price * 100 * row['buy_shares']
        profit = sell_amount - row['buy_amount']
        profit_rate = (profit / row['buy_amount']) * 100

        from datetime import datetime
        now = datetime.now().isoformat()
        await db.execute(
            """UPDATE trades SET
            sell_time = ?, sell_price = ?, sell_amount = ?,
            profit = ?, profit_rate = ?, status = 'SOLD'
            WHERE id = ?""",
            (now, sell_price, sell_amount, profit, profit_rate, trade_id)
        )
        await db.execute(
            "UPDATE signals SET status = 'SETTLED' WHERE id = ?",
            (row['signal_id'],)
        )
        await db.commit()

        return {
            "trade_id": trade_id,
            "sell_price": sell_price,
            "profit": round(profit, 2),
            "profit_rate": round(profit_rate, 4),
        }
