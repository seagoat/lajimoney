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
        await db.commit()
    return await get_settings()
