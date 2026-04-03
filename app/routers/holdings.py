from fastapi import APIRouter, HTTPException
from datetime import datetime
import aiosqlite
import asyncio
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
        return dict(zip([d[0] for d in cursor.description], row))


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
        return dict(zip([d[0] for d in cursor.description], row))


@router.get("/lookup-batch")
async def lookup_batch(codes: str):
    """批量查询多只正股的转债信息（逗号分隔）"""
    from app.services.data_fetcher import get_stock_price, get_cb_info_by_stock, get_cb_info_by_stock_with_price, _get_bulk_prices, _get_bulk_cb_prices
    from app.services.signal_engine import calculate_conversion_value, calculate_premium_rate, calculate_discount_space

    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        return []

    # 批量获取所有正股价格
    stock_prices = await asyncio.to_thread(_get_bulk_prices, code_list)
    # 批量获取所有转债价格
    cb_codes = []
    cb_mapping = {}  # stock_code -> cb_info (无价格)
    for code in code_list:
        cb_info = await asyncio.to_thread(get_cb_info_by_stock, code)
        if cb_info:
            cb_codes.append(cb_info["cb_code"])
            cb_mapping[code] = cb_info

    cb_prices = await asyncio.to_thread(_get_bulk_cb_prices, cb_codes) if cb_codes else {}

    results = []
    for code in code_list:
        stock_data = stock_prices.get(code)
        price = stock_data[0] if stock_data else None
        stock_name = stock_data[1] if stock_data else None
        cb_info = cb_mapping.get(code)
        item = {"stock_code": code, "stock_price": price, "stock_name": stock_name, "cb": None}
        if cb_info and price:
            cb_price = cb_prices.get(cb_info["cb_code"])
            if cb_price:
                cv = calculate_conversion_value(price, cb_info["conversion_price"])
                pr = calculate_premium_rate(cb_price, cv)
                ds = calculate_discount_space(cv, cb_price)
                item["cb"] = {
                    "cb_code": cb_info["cb_code"],
                    "cb_name": cb_info["cb_name"],
                    "cb_price": cb_price,
                    "conversion_price": cb_info["conversion_price"],
                    "conversion_value": round(cv, 4),
                    "premium_rate": round(pr, 4),
                    "discount_space": round(ds, 4),
                }
        results.append(item)

    return results


@router.get("/lookup")
async def lookup_stock(code: str):
    """根据股票代码查询股票名称、实时价格及对应转债信息（用于自动填充）"""
    from app.services.data_fetcher import get_stock_name, get_stock_price, get_cb_info_by_stock_with_price
    from app.services.signal_engine import calculate_conversion_value, calculate_premium_rate, calculate_discount_space

    name = await asyncio.to_thread(get_stock_name, code)
    price = await asyncio.to_thread(get_stock_price, code)
    if name is None and price is None:
        return {"found": False, "stock_code": code, "stock_name": None}

    result = {"found": True, "stock_code": code, "stock_name": name, "stock_price": price, "cb": None}

    cb_info = await asyncio.to_thread(get_cb_info_by_stock_with_price, code)
    if cb_info:
        conversion_value = calculate_conversion_value(price, cb_info["conversion_price"])
        premium_rate = calculate_premium_rate(cb_info["cb_price"], conversion_value)
        discount_space = calculate_discount_space(conversion_value, cb_info["cb_price"])
        result["cb"] = {
            "cb_code": cb_info["cb_code"],
            "cb_name": cb_info["cb_name"],
            "cb_price": cb_info["cb_price"],
            "conversion_price": cb_info["conversion_price"],
            "conversion_value": round(conversion_value, 4),
            "premium_rate": round(premium_rate, 4),
            "discount_space": round(discount_space, 4),
        }

    return result
async def delete_holding(holding_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM holdings WHERE id = ?", (holding_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="底仓不存在")

        await db.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
        await db.commit()
        return {"message": "删除成功"}


@router.delete("", response_model=dict)
async def delete_all_holdings():
    """删除全部底仓"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM holdings")
        await db.commit()
        return {"message": f"已删除全部 {cursor.rowcount} 条底仓记录"}
