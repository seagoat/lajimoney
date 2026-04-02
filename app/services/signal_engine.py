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


def scan_single_stock(stock_code: str, stock_price: float) -> dict | None:
    """
    扫描单只正股对应的转债
    返回信号字典或None（不满足条件）
    """
    from app.services.data_fetcher import get_cb_info_by_stock
    cb_info = get_cb_info_by_stock(stock_code)
    if not cb_info:
        return None

    cb_price = cb_info['cb_price']
    conversion_price = cb_info['conversion_price']
    conversion_value = calculate_conversion_value(stock_price, conversion_price)
    premium_rate = calculate_premium_rate(cb_price, conversion_value)
    discount_space = calculate_discount_space(conversion_value, cb_price)

    # 判断是否满足折价套利条件
    if premium_rate >= DISCOUNT_THRESHOLD:
        return None  # 不满足条件

    return {
        'cb_code': cb_info['cb_code'],
        'cb_name': cb_info['cb_name'],
        'stock_code': stock_code,
        'stock_price': stock_price,
        'cb_price': cb_price,
        'conversion_price': conversion_price,
        'conversion_value': round(conversion_value, 4),
        'premium_rate': round(premium_rate, 4),
        'discount_space': round(discount_space, 4),
        'target_buy_price': round(cb_price, 2),
        'target_shares': TARGET_LOT_SIZE,
    }


def scan_portfolio(stock_codes: list[str]) -> list[dict]:
    """
    扫描一组正股，返回所有满足条件的信号
    按折价空间从大到小排序
    """
    from app.services.data_fetcher import get_stock_price
    signals = []
    for code in stock_codes:
        price = get_stock_price(code)
        if price is None:
            continue
        sig = scan_single_stock(code, price)
        if sig:
            signals.append(sig)

    # 按折价空间降序
    signals.sort(key=lambda x: x['discount_space'], reverse=True)
    return signals
