"""
融券保证金与利息计算引擎
"""


def calc_interest(loan_amount: float, daily_rate: float, days: int) -> float:
    """
    计算融券利息
    loan_amount: 融券卖出总额
    daily_rate: 日利率（小数，如 0.00022）
    days: 计息天数
    """
    return round(loan_amount * daily_rate * days, 2)


def calc_margin_required(loan_amount: float, margin_ratio: float) -> float:
    """
    计算所需保证金
    loan_amount: 融券卖出总额
    margin_ratio: 保证金比例（小数，如 0.5）
    """
    return loan_amount * margin_ratio


def calc_net_profit_short(
    loan_price: float,
    shares: int,
    cb_buy_price: float,
    cb_shares: int,
    cover_price: float,
    conversion_price: float,
    daily_interest_rate: float,
    interest_days: int,
    stock_broker_fee: float,
    cb_broker_fee: float,
    margin_ratio: float
) -> tuple[float, float]:
    """
    SHORT 模式净收益计算
    融券卖出正股 + 买CB + 转股归还 + 利息

    Returns: (net_profit, net_profit_rate_percent)
    """
    # 融券卖出所得
    loan_amount = loan_price * shares

    # CB买入成本（含佣金）
    # 公式保持与 signal_engine.calc_net_profit_* 一致
    cb_buy_amount = cb_buy_price * 100 * cb_shares
    cb_buy_commission = cb_buy_amount * cb_broker_fee
    total_cb_cost = cb_buy_amount + cb_buy_commission

    # 转股获得股数
    shares_from_cb = (100.0 / conversion_price) * cb_shares if conversion_price > 0 else 0

    # 归还买入成本（买股还券）
    cover_amount = cover_price * shares_from_cb
    cover_commission = cover_amount * stock_broker_fee

    # 融券卖出佣金
    loan_commission = loan_amount * stock_broker_fee

    # 融券利息
    interest = calc_interest(loan_amount, daily_interest_rate, interest_days)

    # 净收益 = 卖券所得 - 买CB成本 - 归还成本 - 利息 - 所有佣金
    net_profit = (
        loan_amount
        - total_cb_cost
        - cover_amount
        - interest
        - loan_commission
        - cover_commission
    )

    # 保证金占用作为分母计算收益率
    margin_required = calc_margin_required(cb_buy_amount, margin_ratio)
    net_profit_rate = round(net_profit / margin_required * 100, 4) if margin_required > 0 else 0.0

    return round(net_profit, 2), net_profit_rate
