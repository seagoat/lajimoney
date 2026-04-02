from fastapi import APIRouter, HTTPException
from datetime import datetime
import aiosqlite
from app.models import SettingsResponse, SettingsUpdate
from app.config import DB_PATH

router = APIRouter(prefix="/api/settings", tags=["设置"])


@router.get("", response_model=SettingsResponse)
async def get_settings():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        settings = {r['key']: r['value'] for r in rows}
        return {
            "discount_threshold": float(settings.get("discount_threshold", "-1.0")),
            "target_lot_size": int(settings.get("target_lot_size", "10")),
            "scan_mode": settings.get("scan_mode", "holdings"),
            "stock_broker_fee": float(settings.get("stock_broker_fee", "0.0001")),
            "stock_stamp_tax": float(settings.get("stock_stamp_tax", "0.0015")),
            "cb_broker_fee": float(settings.get("cb_broker_fee", "0.00006")),
            "naked_discount_threshold": float(settings.get("naked_discount_threshold", "-2.0")),
            "naked_enabled": settings.get("naked_enabled", "true") == "true",
        }


@router.put("", response_model=SettingsResponse)
async def update_settings(update: SettingsUpdate):
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        if update.discount_threshold is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("discount_threshold", str(update.discount_threshold), now)
            )
        if update.target_lot_size is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("target_lot_size", str(update.target_lot_size), now)
            )
        if update.scan_mode is not None:
            if update.scan_mode not in ("holdings", "all"):
                raise HTTPException(status_code=400, detail="scan_mode must be 'holdings' or 'all'")
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("scan_mode", update.scan_mode, now)
            )
        if update.stock_broker_fee is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("stock_broker_fee", str(update.stock_broker_fee), now)
            )
        if update.stock_stamp_tax is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("stock_stamp_tax", str(update.stock_stamp_tax), now)
            )
        if update.cb_broker_fee is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("cb_broker_fee", str(update.cb_broker_fee), now)
            )
        if update.naked_discount_threshold is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("naked_discount_threshold", str(update.naked_discount_threshold), now)
            )
        if update.naked_enabled is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("naked_enabled", "true" if update.naked_enabled else "false", now)
            )
        await db.commit()
    return await get_settings()
