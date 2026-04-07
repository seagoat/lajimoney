"""
可转债套利信号计算引擎
"""


def calculate_conversion_value(stock_price: float, conversion_price: float) -> float:
    if conversion_price <= 0:
        return 0.0
    return (100.0 / conversion_price) * stock_price


def calculate_premium_rate(cb_price: float, conversion_value: float) -> float:
    if conversion_value <= 0:
        return 0.0
    return (cb_price / conversion_value - 1) * 100.0


def calculate_discount_space(conversion_value: float, cb_price: float) -> float:
    return conversion_value - cb_price


# ---- 收益计算函数 ----

def calc_net_profit_hedge(buy_price: float, buy_shares: int, sell_price: float,
                          stock_broker_fee: float, stock_stamp_tax: float,
                          cb_broker_fee: float) -> tuple[float, float]:
    """
    持仓对冲模式净收益计算
    卖出股票 - 买入CB - 双向佣金 - 印花税
    Returns: (net_profit, net_profit_rate_percent)
    """
    buy_amount = buy_price * 100 * buy_shares
    sell_amount = sell_price * 100 * buy_shares
    stock_commission = sell_amount * stock_broker_fee
    stamp_tax = sell_amount * stock_stamp_tax
    cb_buy_commission = buy_amount * cb_broker_fee
    cb_sell_commission = sell_amount * cb_broker_fee
    net_profit = sell_amount - buy_amount - stock_commission - stamp_tax - cb_buy_commission - cb_sell_commission
    return net_profit, round(net_profit / buy_amount * 100, 4)


def calc_net_profit_naked(buy_price: float, buy_shares: int,
                          sell_price_open: float, conversion_price: float,
                          stock_broker_fee: float, cb_broker_fee: float) -> tuple[float, float]:
    """
    裸套模式净收益计算
    CB买入 → 转股 → 次日卖出正股
    收益 = 卖出正股所得 - CB买入成本 - CB买入佣金 - 股票卖出佣金
    Returns: (net_profit, net_profit_rate_percent)
    """
    cb_buy_amount = buy_price * 100 * buy_shares
    cb_buy_commission = cb_buy_amount * cb_broker_fee
    total_cost = cb_buy_amount + cb_buy_commission

    shares_from_cb = (100.0 / conversion_price) * buy_shares
    sell_stock_amount = sell_price_open * shares_from_cb
    stock_commission = sell_stock_amount * stock_broker_fee

    net_profit = sell_stock_amount - total_cost - stock_commission
    return net_profit, round(net_profit / total_cost * 100, 4)


# ---- 同步版本（供 trade_engine 持久化成交用） ----

def scan_portfolio(stock_codes: list[str], hedge_threshold: float, target_lot_size: int) -> list[dict]:
    from app.services.data_fetcher import get_stock_price, get_cb_info_by_stock_with_price
    signals = []
    for code in stock_codes:
        price = get_stock_price(code)
        if price is None:
            continue
        cb_info = get_cb_info_by_stock_with_price(code)
        if cb_info is None:
            continue
        cb_price = cb_info['cb_price']
        conversion_price = cb_info['conversion_price']
        conversion_value = calculate_conversion_value(price, conversion_price)
        premium_rate = calculate_premium_rate(cb_price, conversion_value)
        if premium_rate < hedge_threshold:
            signals.append({
                'cb_code': cb_info['cb_code'],
                'cb_name': cb_info['cb_name'],
                'stock_code': code,
                'stock_price': price,
                'cb_price': cb_price,
                'conversion_price': conversion_price,
                'conversion_value': round(conversion_value, 4),
                'premium_rate': round(premium_rate, 4),
                'discount_space': round(calculate_discount_space(conversion_value, cb_price), 4),
                'target_buy_price': round(cb_price, 2),
                'target_shares': target_lot_size,
            })
    signals.sort(key=lambda x: x['discount_space'], reverse=True)
    return signals


# ---- 持仓模式异步扫描 ----

async def scan_portfolio_gen(stock_codes: list[str], hedge_threshold: float, holdings_shares: dict[str, float]):
    """
    异步生成器，逐只正股产出最终状态（持仓模式）
    每只股票只 yield 一次最终状态
    target_shares 按底仓股数换算：ceil(持有股数 × 转股价 ÷ 100 ÷ 10) × 10
    """
    import asyncio, math
    from app.services.data_fetcher import get_stock_price, get_stock_name, get_cb_info_by_stock_with_price

    for i, code in enumerate(stock_codes):
        price, stock_name = await asyncio.gather(
            asyncio.to_thread(get_stock_price, code),
            asyncio.to_thread(get_stock_name, code),
        )

        if price is None:
            yield {
                'step': i + 1,
                'total': len(stock_codes),
                'stock_code': code,
                'status': 'skip',
                'message': f'{code}：无法获取正股价格，跳过',
            }
            continue

        cb_info = await asyncio.to_thread(get_cb_info_by_stock_with_price, code)
        if cb_info is None:
            yield {
                'step': i + 1,
                'total': len(stock_codes),
                'stock_code': code,
                'status': 'skip',
                'message': f'{code} 正股:{price} → 无对应转债或无法获取转债价格，跳过',
                'stock_price': price,
            }
            continue

        cb_price = cb_info['cb_price']
        conversion_price = cb_info['conversion_price']
        conversion_value = calculate_conversion_value(price, conversion_price)
        premium_rate = calculate_premium_rate(cb_price, conversion_value)
        discount_space = calculate_discount_space(conversion_value, cb_price)

        if premium_rate < hedge_threshold:
            # 按底仓股数换算所需CB张数：ceil(持有股数 × 转股价 ÷ 100 ÷ 10) × 10
            held_shares = holdings_shares.get(code, 0)
            if held_shares > 0 and conversion_price > 0:
                raw_lots = held_shares * conversion_price / 100 / 10
                target_shares_calc = math.ceil(raw_lots) * 10
            else:
                target_shares_calc = 10  # fallback 最低10张

            yield {
                'step': i + 1,
                'total': len(stock_codes),
                'stock_code': code,
                'status': 'signal_found',
                'message': f'✅ 发现信号！{stock_name or code} ({code}) 正股:{price} → {cb_info["cb_code"]} 转债:{cb_price} 转股价值:{conversion_value:.2f} 折价:{discount_space:.2f} 溢价率:{premium_rate:.2f}%（匹配底仓:{held_shares}股 → 买入{target_shares_calc}张）',
                'cb_code': cb_info['cb_code'],
                'cb_name': cb_info['cb_name'],
                'stock_code': code,
                'stock_name': stock_name,
                'stock_price': price,
                'cb_price': cb_price,
                'conversion_price': conversion_price,
                'conversion_value': round(conversion_value, 4),
                'premium_rate': round(premium_rate, 4),
                'discount_space': round(discount_space, 4),
                'target_shares': target_shares_calc,
                'held_shares': held_shares,
            }
        else:
            yield {
                'step': i + 1,
                'total': len(stock_codes),
                'stock_code': code,
                'status': 'not_qualified',
                'message': f'{code} 正股:{price} → {cb_info["cb_code"]} 转债:{cb_price} 转股价:{conversion_price} 溢价率:{premium_rate:.2f}%（需<{hedge_threshold}%）',
                'cb_code': cb_info['cb_code'],
                'cb_name': cb_info['cb_name'],
                'stock_price': price,
                'cb_price': cb_price,
                'conversion_price': conversion_price,
                'conversion_value': round(conversion_value, 4),
                'premium_rate': round(premium_rate, 4),
                'discount_space': round(discount_space, 4),
            }


# ---- 全量转债扫描模式 ----

async def scan_all_cb_gen(hedge_threshold: float, short_threshold: float, naked_threshold: float, target_lot_size: int, settings: dict):
    """
    异步生成器，扫描全市场转债（all模式）
    支持裸套模式：底仓为空时使用裸套折价阈值
    """
    import asyncio
    import math
    from app.services.data_fetcher import get_all_cb_with_prices

    yield {
        'step': 0,
        'total': 0,
        'stock_code': '',
        'status': 'loading_cb_list',
        'message': '正在加载全量转债列表...',
    }

    # 检测模式：底仓 > 融券 > 裸套
    from app.routers.signals import load_holdings
    holdings_stocks = await load_holdings()  # dict: {stock_code: shares}
    naked_enabled = settings.get("naked_enabled", "false") == "true"
    short_enabled = settings.get("short_enabled", "false") == "true"

    # 判断是否整体无底仓（用于开头提示）
    if not holdings_stocks and not naked_enabled and not short_enabled:
        yield {
            'step': 0, 'total': 0, 'stock_code': '',
            'status': 'error',
            'message': '底仓为空且融券/裸套模式均未启用，请先添加底仓或开启对应模式',
        }
        return

    all_cb = await asyncio.to_thread(get_all_cb_with_prices)

    # 预加载融资融券标的列表（一次性，从缓存读）
    from app.services.data_fetcher import is_marginable, _load_marginable_stocks
    await asyncio.to_thread(_load_marginable_stocks)

    total = len(all_cb)

    if holdings_stocks:
        mode_msg = f'持仓对冲模式（阈值: {hedge_threshold}%）'
    elif short_enabled:
        mode_msg = f'融券对冲模式（阈值: {short_threshold}%）'
    else:
        mode_msg = f'裸套模式（阈值: {naked_threshold}%）'

    yield {
        'step': 0,
        'total': total,
        'stock_code': '',
        'status': 'loaded',
        'message': f'已加载 {total} 只转债，开始逐只分析... {mode_msg}',
    }

    for i, cb in enumerate(all_cb):
        yield {
            'step': i + 1,
            'total': total,
            'stock_code': cb['stock_code'],
            'status': 'scanning',
            'message': f'[{i+1}/{total}] 正在扫描 {cb["stock_code"]} → {cb["cb_code"]}...',
        }

        stock_price = cb['stock_price']
        stock_name = cb.get('stock_name')
        cb_price = cb['cb_price']
        conversion_price = cb['conversion_price']
        conversion_value = calculate_conversion_value(stock_price, conversion_price)
        premium_rate = calculate_premium_rate(cb_price, conversion_value)
        discount_space = calculate_discount_space(conversion_value, cb_price)

        # 策略池构建
        in_holdings = cb['stock_code'] in holdings_stocks
        short_available = is_marginable(cb['stock_code'])

        # 实际采用策略
        if in_holdings:
            trade_type = 'HEDGE'
            mode_label = '对冲'
        elif short_enabled and short_available:
            trade_type = 'SHORT'
            mode_label = '融券'
        elif naked_enabled:
            trade_type = 'NAKED'
            mode_label = '裸套'
        else:
            trade_type = None
            mode_label = None

        if trade_type and premium_rate < (hedge_threshold if trade_type == 'HEDGE' else (short_threshold if trade_type == 'SHORT' else naked_threshold)):
            # 计算目标张数
            if trade_type == 'HEDGE':
                # 有底仓：按底仓股数换算
                held_shares = holdings_stocks.get(cb['stock_code'], 0)
                if held_shares > 0 and conversion_price > 0:
                    raw_lots = held_shares * conversion_price / 100 / 10
                    target_shares_calc = math.ceil(raw_lots) * 10
                else:
                    target_shares_calc = 10
            elif trade_type == 'SHORT':
                # 融券：按融券资金上限计算
                short_max_fund = float(settings.get("short_max_fund", "100000"))
                raw_shares = int(short_max_fund / (cb_price * 100))
                raw_shares = raw_shares // 10 * 10  # 向下取整到10的倍数
                # 转成CB张数：每100元债值1张，每张债可转 股
                target_shares_calc = max(raw_shares, 10)
            else:
                # NAKED：按裸套资金上限计算
                naked_max_fund = float(settings.get("naked_max_fund", "100000"))
                raw_shares = int(naked_max_fund / (cb_price * 100))
                raw_shares = raw_shares // 10 * 10
                target_shares_calc = max(raw_shares, 10)

            yield {
                'step': i + 1,
                'total': total,
                'stock_code': cb['stock_code'],
                'status': 'signal_found',
                'message': f'✅ 发现信号！[{mode_label}] {stock_name or cb["stock_code"]} ({cb["stock_code"]}) 正股:{stock_price} → {cb["cb_code"]} 转债:{cb_price} 转股价值:{conversion_value:.2f} 折价:{discount_space:.2f} 溢价率:{premium_rate:.2f}%',
                'cb_code': cb['cb_code'],
                'cb_name': cb['cb_name'],
                'stock_code': cb['stock_code'],
                'stock_name': stock_name,
                'stock_price': stock_price,
                'cb_price': cb_price,
                'conversion_price': conversion_price,
                'conversion_value': round(conversion_value, 4),
                'premium_rate': round(premium_rate, 4),
                'discount_space': round(discount_space, 4),
                'target_shares': target_shares_calc,
                'trade_type': trade_type,
                'short_available': short_available,
                'has_holdings': in_holdings,
            }
        else:
            yield {
                'step': i + 1,
                'total': total,
                'stock_code': cb['stock_code'],
                'status': 'not_qualified',
                'message': f'{cb["stock_code"]} 正股:{stock_price} → {cb["cb_code"]} 转债:{cb_price} 转股价:{conversion_price} 溢价率:{premium_rate:.2f}%',
                'cb_code': cb['cb_code'],
                'cb_name': cb['cb_name'],
                'stock_name': stock_name,
                'stock_price': stock_price,
                'cb_price': cb_price,
                'conversion_price': conversion_price,
                'conversion_value': round(conversion_value, 4),
                'premium_rate': round(premium_rate, 4),
                'discount_space': round(discount_space, 4),
                'has_holdings': in_holdings,
            }
