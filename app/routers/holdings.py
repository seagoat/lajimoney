from fastapi import APIRouter, HTTPException
from datetime import datetime
import aiosqlite
from app.config import DB_PATH
from app.models import HoldingCreate, HoldingUpdate, HoldingResponse

router = APIRouter(prefix="/api/holdings", tags=["底仓管理"])


@router.get("", response_model=list[HoldingResponse])
async def list_holdings():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM holdings ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


@router.post("", response_model=HoldingResponse)
async def add_holding(holding: HoldingCreate):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now().isoformat()
        cursor = await db.execute(
            """INSERT INTO holdings (stock_code, stock_name, shares, cost_price, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (holding.stock_code, holding.stock_name, holding.shares,
             holding.cost_price, now, now)
        )
        await db.commit()
        holding_id = cursor.lastrowid

        cursor = await db.execute("SELECT * FROM holdings WHERE id = ?", (holding_id,))
        row = await cursor.fetchone()
        return dict(row)


@router.put("/{holding_id}", response_model=HoldingResponse)
async def update_holding(holding_id: int, update: HoldingUpdate):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM holdings WHERE id = ?", (holding_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="底仓不存在")

        updates = []
        values = []
        if update.stock_name is not None:
            updates.append("stock_name = ?")
            values.append(update.stock_name)
        if update.shares is not None:
            updates.append("shares = ?")
            values.append(update.shares)
        if update.cost_price is not None:
            updates.append("cost_price = ?")
            values.append(update.cost_price)

        updates.append("updated_at = ?")
        values.append(datetime.now().isoformat())
        values.append(holding_id)

        await db.execute(
            f"UPDATE holdings SET {', '.join(updates)} WHERE id = ?",
            values
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM holdings WHERE id = ?", (holding_id,))
        row = await cursor.fetchone()
        return dict(row)


@router.delete("/{holding_id}")
async def delete_holding(holding_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM holdings WHERE id = ?", (holding_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="底仓不存在")

        await db.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
        await db.commit()
        return {"message": "删除成功"}
