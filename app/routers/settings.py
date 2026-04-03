from fastapi import APIRouter, HTTPException
from datetime import datetime
import aiosqlite
from app.models import SettingsResponse, SettingsUpdate, MarginSettingsUpdate
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
            "short_enabled": settings.get("short_enabled", "false") == "true",
            "short_max_fund": float(settings.get("short_max_fund", "100000")),
            "naked_max_fund": float(settings.get("naked_max_fund", "100000")),
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
        if update.short_enabled is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("short_enabled", "true" if update.short_enabled else "false", now)
            )
        if update.short_max_fund is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("short_max_fund", str(update.short_max_fund), now)
            )
        if update.naked_max_fund is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("naked_max_fund", str(update.naked_max_fund), now)
            )
        await db.commit()
    return await get_settings()


@router.get("/margin-settings")
async def get_margin_settings():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM margin_settings WHERE id = 1")
        row = await cursor.fetchone()
        if not row:
            return {
                "id": None,
                "broker_name": "",
                "margin_ratio": 0.5,
                "daily_interest_rate": 0.00022,
                "force_liquidation_ratio": 1.3,
            }
        return dict(zip([d[0] for d in cursor.description], row))


@router.put("/margin-settings")
async def update_margin_settings(update: MarginSettingsUpdate):
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        updates = []
        values = []
        if update.broker_name is not None:
            updates.append("broker_name = ?")
            values.append(update.broker_name)
        if update.margin_ratio is not None:
            updates.append("margin_ratio = ?")
            values.append(update.margin_ratio)
            # 同时更新 settings 表
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('margin_ratio', ?)",
                (str(update.margin_ratio),)
            )
        if update.daily_interest_rate is not None:
            updates.append("daily_interest_rate = ?")
            values.append(update.daily_interest_rate)
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('margin_daily_interest', ?)",
                (str(update.daily_interest_rate),)
            )
        if update.force_liquidation_ratio is not None:
            updates.append("force_liquidation_ratio = ?")
            values.append(update.force_liquidation_ratio)
        updates.append("updated_at = ?")
        values.append(now)
        await db.execute(
            f"UPDATE margin_settings SET {', '.join(updates)} WHERE id = 1",
            values
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM margin_settings WHERE id = 1")
        row = await cursor.fetchone()
        return dict(zip([d[0] for d in cursor.description], row))
