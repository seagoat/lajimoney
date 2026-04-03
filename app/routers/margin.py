from fastapi import APIRouter, HTTPException
from datetime import datetime
import aiosqlite
from app.config import DB_PATH
from app.models import LoanPositionResponse

router = APIRouter(prefix="/api/margin", tags=["融券管理"])


@router.get("/positions", response_model=list[LoanPositionResponse])
async def list_loan_positions(status: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = "WHERE status = ?" if status else ""
        params = [status] if status else []
        cursor = await db.execute(
            f"SELECT * FROM loan_positions {where} ORDER BY created_at DESC",
            params
        )
        rows = await cursor.fetchall()
        return [dict(zip([d[0] for d in cursor.description], r)) for r in rows]


@router.delete("/{position_id}")
async def close_loan_position(position_id: int):
    """手动平仓融券仓位（模拟归还）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM loan_positions WHERE id = ?", (position_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="融券仓位不存在")
        if row['status'] == 'COVERED':
            raise HTTPException(status_code=400, detail="该仓位已平仓")

        now = datetime.now().isoformat()
        cover_price = round(row['loan_price'] * 0.999, 2)
        cover_amount = round(cover_price * row['shares'], 2)
        interest_fee = round(row['loan_amount'] * row['interest_rate'] * row['interest_days'], 2)

        await db.execute(
            """UPDATE loan_positions SET
            status = 'COVERED', cover_time = ?, cover_price = ?,
            cover_amount = ?, interest_fee = ?, updated_at = ?
            WHERE id = ?""",
            (now, cover_price, cover_amount, interest_fee, now, position_id)
        )
        await db.commit()
        return {"message": "平仓成功", "cover_price": cover_price, "interest_fee": interest_fee}


@router.delete("/positions/all", response_model=dict)
async def close_all_loan_positions():
    """全部平仓融券仓位"""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now().isoformat()
        cursor = await db.execute(
            "UPDATE loan_positions SET status = 'COVERED', cover_time = ?, cover_price = loan_price, cover_amount = loan_amount, updated_at = ? WHERE status = 'ACTIVE'",
            (now, now)
        )
        await db.commit()
        return {"message": f"已全部平仓 {cursor.rowcount} 个融券仓位"}
