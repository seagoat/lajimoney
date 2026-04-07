"""
模拟成交执行引擎
"""
import aiosqlite
from datetime import datetime
from app.config import DB_PATH
from app.services.signal_engine import scan_portfolio, calc_net_profit_hedge, calc_net_profit_naked
from app.services.margin_engine import calc_net_profit_short


async def execute_scan_and_trade():
    """
    执行一次完整的扫描 + 模拟买入（使用当前设置）
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 读取设置
        cursor = await db.execute("SELECT key, value FROM settings")
        settings = {r['key']: r['value'] for r in await cursor.fetchall()}
        hedge_threshold = float(settings.get("hedge_discount_threshold", "-0.3"))
        target_lot_size = int(settings.get("target_lot_size", "10"))

        # 1. 获取持仓正股列表
        cursor = await db.execute("SELECT stock_code FROM holdings")
        rows = await cursor.fetchall()
        stock_codes = [r['stock_code'] for r in rows]

        if not stock_codes:
            return {"status": "no_holdings", "signals": []}

        # 2. 执行扫描
        signals = scan_portfolio(stock_codes, hedge_threshold, target_lot_size)

        # 3. 记录扫描日志
        now = datetime.now()
        cursor = await db.execute(
            "INSERT INTO scan_log (scan_time, target_stocks, signals_found, status) VALUES (?, ?, ?, ?)",
            (now.isoformat(), ','.join(stock_codes), len(signals), 'SUCCESS')
        )
        scan_log_id = cursor.lastrowid

        # 4. 记录信号并模拟买入
        executed_trades = []
        for sig in signals:
            cursor = await db.execute(
                """INSERT INTO signals
                (scan_log_id, cb_code, cb_name, stock_code, stock_price, cb_price,
                 conversion_price, conversion_value, premium_rate, discount_space,
                 target_buy_price, target_shares, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
                (scan_log_id, sig['cb_code'], sig['cb_name'], sig['stock_code'],
                 sig['stock_price'], sig['cb_price'], sig['conversion_price'],
                 sig['conversion_value'], sig['premium_rate'], sig['discount_space'],
                 sig['target_buy_price'], sig['target_shares'])
            )
            signal_id = cursor.lastrowid

            # 模拟成交：买入
            buy_amount = sig['target_buy_price'] * 100 * sig['target_shares']
            cursor = await db.execute(
                """INSERT INTO trades
                (signal_id, cb_code, cb_name, buy_time, buy_price, buy_shares, buy_amount, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
                (signal_id, sig['cb_code'], sig['cb_name'],
                 now.isoformat(), sig['target_buy_price'], sig['target_shares'], buy_amount)
            )
            trade_id = cursor.lastrowid

            # 更新信号状态为已执行
            await db.execute(
                "UPDATE signals SET status = 'EXECUTED' WHERE id = ?",
                (signal_id,)
            )

            executed_trades.append({
                'signal_id': signal_id,
                'trade_id': trade_id,
                'cb_code': sig['cb_code'],
                'cb_name': sig['cb_name'],
                'buy_price': sig['target_buy_price'],
                'buy_shares': sig['target_shares'],
                'buy_amount': buy_amount,
                'premium_rate': sig['premium_rate'],
                'discount_space': sig['discount_space'],
            })

        await db.commit()

        return {
            "status": "success",
            "scan_log_id": scan_log_id,
            "signals_found": len(signals),
            "trades": executed_trades,
        }


async def settle_pending_trades():
    """
    对所有 PENDING 状态的持仓执行卖出
    模拟次日开盘卖出
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT * FROM trades WHERE status = 'PENDING'"
        )
        rows = await cursor.fetchall()

        results = []
        for row in rows:
            trade_id = row['id']
            cb_code = row['cb_code']
            trade_type = row.get('trade_type', 'HEDGE')

            # 读取交易成本设置
            cost_cursor = await db.execute(
                "SELECT key, value FROM settings WHERE key IN ('stock_broker_fee','stock_stamp_tax','cb_broker_fee','margin_ratio','margin_daily_interest')"
            )
            cost_rows = await cost_cursor.fetchall()
            cost_settings = {r['key']: float(r['value']) for r in cost_rows}
            stock_broker_fee = cost_settings.get('stock_broker_fee', 0.0001)
            stock_stamp_tax = cost_settings.get('stock_stamp_tax', 0.0015)
            cb_broker_fee = cost_settings.get('cb_broker_fee', 0.00006)
            margin_ratio = cost_settings.get('margin_ratio', 0.5)
            margin_daily_interest = cost_settings.get('margin_daily_interest', 0.00022)

            # 模拟卖出：简化处理用买入价*1.001模拟次日开盘价
            sell_price = round(row['buy_price'] * 1.001, 2)

            if trade_type == 'NAKED':
                # 裸套：CB买入 → 转股 → 次日卖出正股
                conversion_price = row.get('conversion_price') or row.get('cb_price', 100.0)
                if not conversion_price or conversion_price <= 0:
                    conversion_price = 100.0
                net_profit, net_profit_rate = calc_net_profit_naked(
                    row['buy_price'], row['buy_shares'],
                    sell_price, conversion_price,
                    stock_broker_fee, cb_broker_fee
                )
                profit = net_profit
                profit_rate = net_profit_rate
                sell_amount = round(
                    sell_price * (100.0 / conversion_price) * row['buy_shares']
                    - sell_price * (100.0 / conversion_price) * row['buy_shares'] * stock_broker_fee,
                    2
                )
            elif trade_type == 'SHORT':
                # 融券对冲：融券卖出 → CB买入转股 → 归还融券
                conversion_price = row.get('conversion_price') or row.get('cb_price', 100.0)
                if not conversion_price or conversion_price <= 0:
                    conversion_price = 100.0

                # 获取融券仓位信息
                short_pos_id = row.get('short_position_id')
                if short_pos_id:
                    loan_cursor = await db.execute(
                        "SELECT * FROM loan_positions WHERE id = ?",
                        (short_pos_id,)
                    )
                    loan_row = await loan_cursor.fetchone()
                else:
                    loan_row = None

                if loan_row:
                    loan_price = loan_row['loan_price']
                    shares_from_loan = loan_row['shares']
                    daily_interest_rate = loan_row['interest_rate']
                    interest_days = loan_row['interest_days']
                else:
                    # fallback：按CB换股数量估算
                    loan_price = row.get('stock_price', row['buy_price'])
                    shares_from_loan = int((100.0 / conversion_price) * row['buy_shares'])
                    daily_interest_rate = margin_daily_interest
                    interest_days = 1

                net_profit, net_profit_rate = calc_net_profit_short(
                    loan_price=loan_price,
                    shares=shares_from_loan,
                    cb_buy_price=row['buy_price'],
                    cb_shares=row['buy_shares'],
                    cover_price=sell_price,
                    conversion_price=conversion_price,
                    daily_interest_rate=daily_interest_rate,
                    interest_days=interest_days,
                    stock_broker_fee=stock_broker_fee,
                    cb_broker_fee=cb_broker_fee,
                    margin_ratio=margin_ratio
                )
                profit = net_profit
                profit_rate = net_profit_rate
                sell_amount = round(sell_price * shares_from_loan, 2)

                # 平掉融券仓位
                if loan_row and short_pos_id:
                    now_str = datetime.now().isoformat()
                    cover_amount = round(sell_price * shares_from_loan, 2)
                    interest_fee = round(loan_row['loan_amount'] * daily_interest_rate * interest_days, 2)
                    await db.execute(
                        """UPDATE loan_positions SET
                        status = 'COVERED', cover_time = ?, cover_price = ?,
                        cover_amount = ?, interest_fee = ?, interest_days = ?,
                        updated_at = ?
                        WHERE id = ?""",
                        (now_str, sell_price, cover_amount, interest_fee, interest_days, now_str, short_pos_id)
                    )
            else:
                # 持仓对冲：卖出正股覆盖成本
                net_profit, net_profit_rate = calc_net_profit_hedge(
                    row['buy_price'], row['buy_shares'], sell_price,
                    stock_broker_fee, stock_stamp_tax, cb_broker_fee
                )
                profit = net_profit
                profit_rate = net_profit_rate
                sell_amount = sell_price * 100 * row['buy_shares']

            now = datetime.now()
            await db.execute(
                """UPDATE trades SET
                sell_time = ?, sell_price = ?, sell_amount = ?,
                profit = ?, profit_rate = ?, status = 'SOLD'
                WHERE id = ?""",
                (now.isoformat(), sell_price, sell_amount, profit, profit_rate, trade_id)
            )

            # 更新信号状态
            await db.execute(
                "UPDATE signals SET status = 'SETTLED' WHERE id = ?",
                (row['signal_id'],)
            )

            results.append({
                'trade_id': trade_id,
                'cb_code': cb_code,
                'profit': round(profit, 2),
                'profit_rate': round(profit_rate, 4),
            })

        await db.commit()
        return results
