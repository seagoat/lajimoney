"""
可转债套利信号计算引擎
"""
from app.config import DISCOUNT_THRESHOLD, TARGET_LOT_SIZE


def calculate_conversion_value(stock_price: float, conversion_price: float) -> float:
    """
    转股价值 = (100 / 转股价) * 正股价
    """
    if conversion_price <= 0:
        return 0.0
    return (100.0 / conversion_price) * stock_price


def calculate_premium_rate(cb_price: float, conversion_value: float) -> float:
    """
    溢价率 = (转债市价 / 转股价值 - 1) * 100
    """
    if conversion_value <= 0:
        return 0.0
    return (cb_price / conversion_value - 1) * 100.0


def calculate_discount_space(conversion_value: float, cb_price: float) -> float:
    """
    折价空间 = 转股价值 - 转债市价
    """
    return conversion_value - cb_price


def scan_portfolio(stock_codes: list[str]) -> list[dict]:
    """
    扫描一组正股，返回所有满足条件的信号（同步版本，供 trade_engine 使用）
    """
    from app.services.data_fetcher import get_stock_price, get_cb_info_by_stock
    signals = []
    for code in stock_codes:
        price = get_stock_price(code)
        if price is None:
            continue
        cb_info = get_cb_info_by_stock(code)
        if cb_info is None:
            continue
        cb_price = cb_info['cb_price']
        conversion_price = cb_info['conversion_price']
        conversion_value = calculate_conversion_value(price, conversion_price)
        premium_rate = calculate_premium_rate(cb_price, conversion_value)
        if premium_rate < DISCOUNT_THRESHOLD:
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
                'target_shares': TARGET_LOT_SIZE,
            })
    signals.sort(key=lambda x: x['discount_space'], reverse=True)
    return signals


async def scan_portfolio_gen(stock_codes: list[str]):
    """
    异步生成器，逐只正股产出扫描状态
    """
    from app.services.data_fetcher import get_stock_price, get_cb_info_by_stock

    for i, code in enumerate(stock_codes):
        step = {
            'step': i + 1,
            'total': len(stock_codes),
            'stock_code': code,
            'status': 'fetching_price',
            'message': f'正在获取 {code} 正股价格...',
        }
        yield step

        price = get_stock_price(code)
        if price is None:
            step.update({
                'status': 'skip',
                'message': f'{code}：无法获取正股价格，跳过',
            })
            yield step
            continue

        step.update({
            'status': 'price_ok',
            'message': f'{code} 正股价格: {price}，正在查询转债...',
            'stock_price': price,
        })
        yield step

        cb_info = get_cb_info_by_stock(code)
        if cb_info is None:
            step.update({
                'status': 'skip',
                'message': f'{code}：无对应转债，跳过',
            })
            yield step
            continue

        cb_price = cb_info['cb_price']
        conversion_price = cb_info['conversion_price']
        conversion_value = calculate_conversion_value(price, conversion_price)
        premium_rate = calculate_premium_rate(cb_price, conversion_value)
        discount_space = calculate_discount_space(conversion_value, cb_price)

        if premium_rate < DISCOUNT_THRESHOLD:
            step.update({
                'status': 'signal_found',
                'message': f'✅ 发现信号！{code} → {cb_info["cb_code"]} 溢价率 {premium_rate:.2f}% 折价空间 {discount_space:.2f}',
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
                'message': f'{code} → {cb_info["cb_code"]} 溢价率 {premium_rate:.2f}%（需<{DISCOUNT_THRESHOLD}%），不满足条件',
                'cb_code': cb_info['cb_code'],
                'cb_name': cb_info['cb_name'],
                'cb_price': cb_price,
                'conversion_price': conversion_price,
                'conversion_value': round(conversion_value, 4),
                'premium_rate': round(premium_rate, 4),
                'discount_space': round(discount_space, 4),
            })
        yield step

