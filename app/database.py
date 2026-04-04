import aiosqlite
from app.config import DB_PATH


async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # 创建所有表（如果不存在）
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL UNIQUE,
                stock_name TEXT NOT NULL,
                shares REAL NOT NULL,
                cost_price REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS scan_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_time TIMESTAMP NOT NULL,
                target_stocks TEXT,
                signals_found INTEGER DEFAULT 0,
                status TEXT DEFAULT 'SUCCESS'
            );

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_log_id INTEGER,
                cb_code TEXT NOT NULL,
                cb_name TEXT,
                stock_code TEXT NOT NULL,
                stock_price REAL,
                cb_price REAL,
                conversion_price REAL,
                conversion_value REAL,
                premium_rate REAL,
                discount_space REAL,
                target_buy_price REAL,
                target_shares INTEGER,
                signal_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'PENDING',
                FOREIGN KEY (scan_log_id) REFERENCES scan_log(id)
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER,
                cb_code TEXT NOT NULL,
                cb_name TEXT,
                buy_time TIMESTAMP,
                buy_price REAL,
                buy_shares INTEGER,
                buy_amount REAL,
                sell_time TIMESTAMP,
                sell_price REAL,
                sell_amount REAL,
                profit REAL,
                profit_rate REAL,
                status TEXT DEFAULT 'PENDING',
                FOREIGN KEY (signal_id) REFERENCES signals(id)
            );

            CREATE TABLE IF NOT EXISTS daily_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date DATE UNIQUE,
                total_signals INTEGER DEFAULT 0,
                total_executed INTEGER DEFAULT 0,
                total_profit REAL DEFAULT 0.0,
                win_rate REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.commit()

        # 迁移：新增列和设置（兼容已存在的数据库）
        # signals 表新增 stock_name, trade_type, has_holdings 字段
        cursor = await db.execute("PRAGMA table_info(signals)")
        signal_cols = [row[1] for row in await cursor.fetchall()]
        if 'stock_name' not in signal_cols:
            await db.execute("ALTER TABLE signals ADD COLUMN stock_name TEXT")
        if 'trade_type' not in signal_cols:
            await db.execute("ALTER TABLE signals ADD COLUMN trade_type TEXT DEFAULT 'HEDGE'")
        if 'has_holdings' not in signal_cols:
            await db.execute("ALTER TABLE signals ADD COLUMN has_holdings INTEGER DEFAULT 0")
        if 'next_day_open_price' not in signal_cols:
            await db.execute("ALTER TABLE signals ADD COLUMN next_day_open_price REAL")
        if 'actual_profit' not in signal_cols:
            await db.execute("ALTER TABLE signals ADD COLUMN actual_profit REAL")
        if 'actual_profit_rate' not in signal_cols:
            await db.execute("ALTER TABLE signals ADD COLUMN actual_profit_rate REAL")
        if 'realtime_review_price' not in signal_cols:
            await db.execute("ALTER TABLE signals ADD COLUMN realtime_review_price REAL")
        if 'reviewed_at' not in signal_cols:
            await db.execute("ALTER TABLE signals ADD COLUMN reviewed_at TEXT")
        if 'realtime_actual_profit' not in signal_cols:
            await db.execute("ALTER TABLE signals ADD COLUMN realtime_actual_profit REAL")
        if 'realtime_actual_profit_rate' not in signal_cols:
            await db.execute("ALTER TABLE signals ADD COLUMN realtime_actual_profit_rate REAL")

        await db.commit()

        # 插入新的 settings（IGNORE 跳过已存在的 key）
        new_settings = [
            ('stock_broker_fee', '0.0001'),
            ('stock_stamp_tax', '0.0015'),
            ('cb_broker_fee', '0.00006'),
            ('naked_discount_threshold', '-2.0'),
            ('naked_enabled', 'true'),
            ('scan_interval', '5'),
        ]
        for key, value in new_settings:
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )

        # 确保旧的 settings 也有默认值
        old_settings = [
            ('discount_threshold', '-1.0'),
            ('target_lot_size', '10'),
            ('scan_mode', 'all'),
        ]
        for key, value in old_settings:
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )
        await db.commit()

        # trades 表新增 conversion_price 列
        cursor = await db.execute("PRAGMA table_info(trades)")
        existing_trade_cols = [row[1] for row in await cursor.fetchall()]
        if 'conversion_price' not in existing_trade_cols:
            await db.execute("ALTER TABLE trades ADD COLUMN conversion_price REAL")

        # 新增 settings
        new_margin_settings = [
            ('short_enabled', 'false'),
            ('short_max_fund', '100000'),
            ('naked_max_fund', '100000'),
        ]
        for key, value in new_margin_settings:
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )
        await db.commit()
