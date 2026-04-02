from fastapi import APIRouter, Query
from datetime import date
import aiosqlite
from app.models import DailySummaryResponse, OverviewResponse
from app.config import DB_PATH

router = APIRouter(prefix="/api", tags=["概览与汇总"])


async def get_overview() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 总收益
        cursor = await db.execute(
            "SELECT SUM(profit) as total FROM trades WHERE status = 'SOLD'"
        )
        row = await cursor.fetchone()
        total_profit = row['total'] or 0.0

        # 总成交数
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE status = 'SOLD'"
        )
        row = await cursor.fetchone()
        total_trades = row['cnt']

        # 胜率
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE status = 'SOLD' AND profit > 0"
        )
        row = await cursor.fetchone()
        win_count = row['cnt']
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0.0

        # 待处理持仓数
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE status = 'PENDING'"
        )
        row = await cursor.fetchone()
        pending_count = row['cnt']

        # 今日信号数
        today = date.today().isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM signals WHERE date(signal_time) = ?",
            (today,)
        )
        row = await cursor.fetchone()
        today_signals = row['cnt']

        return {
            "total_profit": round(total_profit, 2),
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "pending_count": pending_count,
            "today_signals": today_signals,
        }


@router.get("/overview", response_model=OverviewResponse)
async def overview():
    return await get_overview()


@router.get("/daily-summary", response_model=list[DailySummaryResponse])
async def list_daily_summary(
    limit: int = Query(30, le=100),
    offset: int = Query(0, ge=0),
):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM daily_summary ORDER BY trade_date DESC LIMIT ? OFFSET ?",
            (limit, offset)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
