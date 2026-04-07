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
            "hedge_discount_threshold": float(settings.get("hedge_discount_threshold", "-0.3")),
            "short_discount_threshold": float(settings.get("short_discount_threshold", "-2.0")),
            "naked_discount_threshold": float(settings.get("naked_discount_threshold", "-2.0")),
            "target_lot_size": int(settings.get("target_lot_size", "10")),
            "scan_mode": settings.get("scan_mode", "all"),
            "stock_broker_fee": float(settings.get("stock_broker_fee", "0.0001")),
            "stock_stamp_tax": float(settings.get("stock_stamp_tax", "0.0015")),
            "cb_broker_fee": float(settings.get("cb_broker_fee", "0.00006")),
            "naked_enabled": settings.get("naked_enabled", "true") == "true",
            "short_enabled": settings.get("short_enabled", "false") == "true",
            "short_max_fund": float(settings.get("short_max_fund", "100000")),
            "naked_max_fund": float(settings.get("naked_max_fund", "100000")),
            "scan_interval": int(settings.get("scan_interval", "5")),
            "auto_scan_enabled": settings.get("auto_scan_enabled", "true") == "true",
        }


@router.put("", response_model=SettingsResponse)
async def update_settings(update: SettingsUpdate):
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        if update.hedge_discount_threshold is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("hedge_discount_threshold", str(update.hedge_discount_threshold), now)
            )
        if update.short_discount_threshold is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("short_discount_threshold", str(update.short_discount_threshold), now)
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
        if update.scan_interval is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("scan_interval", str(update.scan_interval), now)
            )
        if update.auto_scan_enabled is not None:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("auto_scan_enabled", "true" if update.auto_scan_enabled else "false", now)
            )
        await db.commit()

    # 通知 scheduler 更新状态
    if update.auto_scan_enabled is not None or update.scan_interval is not None:
        from app.services.scheduler import update_scheduler_config
        s = await get_settings()
        update_scheduler_config(s.get("auto_scan_enabled", True), s.get("scan_interval", 5))

    # 设置变更后立即触发一次扫描
    from app.services.scheduler import _do_scan
    import asyncio
    asyncio.create_task(_do_scan())

    return await get_settings()


@router.get("/margin-settings")
async def get_margin_settings():
    """获取券商保证金设置"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        settings = {r['key']: r['value'] for r in rows}
        return {
            "broker_name": settings.get("broker_name", ""),
            "margin_ratio": float(settings.get("margin_ratio", "0.5")),
            "daily_interest_rate": float(settings.get("daily_interest_rate", "0.00022")),
            "force_liquidation_ratio": float(settings.get("force_liquidation_ratio", "1.3")),
        }


@router.put("/margin-settings")
async def update_margin_settings(body: dict):
    """更新券商保证金设置"""
    now = datetime.now().isoformat()
    fields = {
        "broker_name": str(body.get("broker_name", "默认券商")),
        "margin_ratio": str(body.get("margin_ratio", "0.5")),
        "daily_interest_rate": str(body.get("daily_interest_rate", "0.00022")),
        "force_liquidation_ratio": str(body.get("force_liquidation_ratio", "1.3")),
    }
    async with aiosqlite.connect(DB_PATH) as db:
        for key, value in fields.items():
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now)
            )
        await db.commit()
    return {"message": "保证金设置已保存"}


