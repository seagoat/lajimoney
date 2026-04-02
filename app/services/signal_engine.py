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


# ---- 同步版本（供 trade_engine 持久化成交用） ----

def scan_portfolio(stock_codes: list[str], discount_threshold: float, target_lot_size: int) -> list[dict]:
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
        if premium_rate < discount_threshold:
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

async def scan_portfolio_gen(stock_codes: list[str], discount_threshold: float, target_lot_size: int):
    """
    异步生成器，逐只正股产出扫描状态（持仓模式）
    """
    import asyncio
    from app.services.data_fetcher import get_stock_price, get_cb_info_by_stock_with_price

    for i, code in enumerate(stock_codes):
        step = {
            'step': i + 1,
            'total': len(stock_codes),
            'stock_code': code,
            'status': 'scanning',
            'message': f'正在扫描 {code}...',
        }
        yield step

        price = await asyncio.to_thread(get_stock_price, code)
        if price is None:
            step.update({
                'status': 'skip',
                'message': f'{code}：无法获取正股价格，跳过',
            })
            yield step
            continue

        cb_info = await asyncio.to_thread(get_cb_info_by_stock_with_price, code)
        if cb_info is None:
            step.update({
                'status': 'skip',
                'message': f'{code} 正股:{price} → 无对应转债或无法获取转债价格，跳过',
                'stock_price': price,
            })
            yield step
            continue

        cb_price = cb_info['cb_price']
        conversion_price = cb_info['conversion_price']
        conversion_value = calculate_conversion_value(price, conversion_price)
        premium_rate = calculate_premium_rate(cb_price, conversion_value)
        discount_space = calculate_discount_space(conversion_value, cb_price)

        if premium_rate < discount_threshold:
            step.update({
                'status': 'signal_found',
                'message': f'✅ 发现信号！{code} 正股:{price} → {cb_info["cb_code"]} 转债:{cb_price} 转股价值:{conversion_value:.2f} 折价:{discount_space:.2f} 溢价率:{premium_rate:.2f}%',
                'cb_code': cb_info['cb_code'],
                'cb_name': cb_info['cb_name'],
                'cb_price': cb_price,
                'conversion_price': conversion_price,
                'conversion_value': round(conversion_value, 4),
                'premium_rate': round(premium_rate, 4),
                'discount_space': round(discount_space, 4),
            })
        else:
            step.update({
                'status': 'not_qualified',
                'message': f'{code} 正股:{price} → {cb_info["cb_code"]} 转债:{cb_price} 转股价:{conversion_price} 溢价率:{premium_rate:.2f}%（需<{discount_threshold}%）',
                'cb_code': cb_info['cb_code'],
                'cb_name': cb_info['cb_name'],
                'cb_price': cb_price,
                'conversion_price': conversion_price,
                'conversion_value': round(conversion_value, 4),
                'premium_rate': round(premium_rate, 4),
                'discount_space': round(discount_space, 4),
            })
        yield step


# ---- 全量转债扫描模式 ----

async def scan_all_cb_gen(discount_threshold: float, target_lot_size: int):
    """
    异步生成器，扫描全市场转债（all模式）
    """
    import asyncio
    from app.services.data_fetcher import get_all_cb_with_prices

    yield {
        'step': 0,
        'total': 0,
        'stock_code': '',
        'status': 'loading_cb_list',
        'message': '正在加载全量转债列表...',
    }

    all_cb = await asyncio.to_thread(get_all_cb_with_prices)
    total = len(all_cb)

    yield {
        'step': 0,
        'total': total,
        'stock_code': '',
        'status': 'loaded',
        'message': f'已加载 {total} 只转债，开始逐只分析...',
    }

    for i, cb in enumerate(all_cb):
        step = {
            'step': i + 1,
            'total': total,
            'stock_code': cb['stock_code'],
            'status': 'scanning',
            'message': f'[{i+1}/{total}] 正在扫描 {cb["stock_code"]} → {cb["cb_code"]}...',
        }
        yield step

        stock_price = cb['stock_price']
        cb_price = cb['cb_price']
        conversion_price = cb['conversion_price']
        conversion_value = calculate_conversion_value(stock_price, conversion_price)
        premium_rate = calculate_premium_rate(cb_price, conversion_value)
        discount_space = calculate_discount_space(conversion_value, cb_price)

        if premium_rate < discount_threshold:
            step.update({
                'status': 'signal_found',
                'message': f'✅ 发现信号！{cb["stock_code"]} 正股:{stock_price} → {cb["cb_code"]} 转债:{cb_price} 转股价值:{conversion_value:.2f} 折价:{discount_space:.2f} 溢价率:{premium_rate:.2f}%',
                'cb_code': cb['cb_code'],
                'cb_name': cb['cb_name'],
                'cb_price': cb_price,
                'conversion_price': conversion_price,
                'conversion_value': round(conversion_value, 4),
                'premium_rate': round(premium_rate, 4),
                'discount_space': round(discount_space, 4),
            })
        else:
            step.update({
                'status': 'not_qualified',
                'message': f'{cb["stock_code"]} 正股:{stock_price} → {cb["cb_code"]} 转债:{cb_price} 转股价:{conversion_price} 溢价率:{premium_rate:.2f}%（需<{discount_threshold}%）',
                'cb_code': cb['cb_code'],
                'cb_name': cb['cb_name'],
                'cb_price': cb_price,
                'conversion_price': conversion_price,
                'conversion_value': round(conversion_value, 4),
                'premium_rate': round(premium_rate, 4),
                'discount_space': round(discount_space, 4),
            })
        yield step
