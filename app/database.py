import aiosqlite
from app.config import DB_PATH


async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
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
        """)
        await db.commit()
