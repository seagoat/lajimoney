async def scan_portfolio_gen(stock_codes: list[str], discount_threshold: float, target_lot_size: int):
    """
    异步生成器，逐只正股产出最终状态（持仓模式）
    每只股票只 yield 一次最终状态
    """
    import asyncio
    from app.services.data_fetcher import get_stock_price, get_cb_info_by_stock_with_price

    for i, code in enumerate(stock_codes):
        # 立即 yield 最终状态，不需要单独的 scanning 中间步骤
        price = await asyncio.to_thread(get_stock_price, code)

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

        if premium_rate < discount_threshold:
            yield {
                'step': i + 1,
                'total': len(stock_codes),
                'stock_code': code,
                'status': 'signal_found',
                'message': f'✅ 发现信号！{code} 正股:{price} → {cb_info["cb_code"]} 转债:{cb_price} 转股价值:{conversion_value:.2f} 折价:{discount_space:.2f} 溢价率:{premium_rate:.2f}%',
                'cb_code': cb_info['cb_code'],
                'cb_name': cb_info['cb_name'],
                'stock_price': price,
                'cb_price': cb_price,
                'conversion_price': conversion_price,
                'conversion_value': round(conversion_value, 4),
                'premium_rate': round(premium_rate, 4),
                'discount_space': round(discount_space, 4),
            }
        else:
            yield {
                'step': i + 1,
                'total': len(stock_codes),
                'stock_code': code,
                'status': 'not_qualified',
                'message': f'{code} 正股:{price} → {cb_info["cb_code"]} 转债:{cb_price} 转股价:{conversion_price} 溢价率:{premium_rate:.2f}%（需<{discount_threshold}%）',
                'cb_code': cb_info['cb_code'],
                'cb_name': cb_info['cb_name'],
                'stock_price': price,
                'cb_price': cb_price,
                'conversion_price': conversion_price,
                'conversion_value': round(conversion_value, 4),
                'premium_rate': round(premium_rate, 4),
                'discount_space': round(discount_space, 4),
            }
