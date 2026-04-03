from fastapi import APIRouter, Query
from datetime import date
import aiosqlite
from app.models import DailySummaryResponse, OverviewResponse
from app.config import DB_PATH

router = APIRouter(prefix="/api", tags=["概览与汇总"])


async def get_overview() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 总信号数
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM signals")
        row = await cursor.fetchone()
        total_signals = row['cnt']

        # 今日信号数
        today = date.today().isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM signals WHERE date(signal_time) = ?",
            (today,)
        )
        row = await cursor.fetchone()
        today_signals = row['cnt']

        # 待处理信号数
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM signals WHERE status = 'PENDING'"
        )
        row = await cursor.fetchone()
        pending_count = row['cnt']

        return {
            "total_profit": total_signals,
            "total_trades": today_signals,
            "win_rate": 0.0,
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
