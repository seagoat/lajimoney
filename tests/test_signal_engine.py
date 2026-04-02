import pytest
from app.services.signal_engine import (
    calculate_conversion_value,
    calculate_premium_rate,
    calculate_discount_space,
)


def test_conversion_value():
    # 转股价值 = (100 / 转股价) * 正股价
    # (100 / 10) * 8 = 800
    assert calculate_conversion_value(8.0, 10.0) == 800.0


def test_conversion_value_zero_price():
    assert calculate_conversion_value(0.0, 10.0) == 0.0


def test_premium_rate_positive():
    # 溢价：转债贵了
    # (10 / 8 - 1) * 100 = 25%
    assert calculate_premium_rate(10.0, 8.0) == 25.0


def test_premium_rate_negative():
    # 折价：转债便宜了
    # (8 / 10 - 1) * 100 = -20%
    assert calculate_premium_rate(8.0, 10.0) == -20.0


def test_premium_rate_zero_conversion_value():
    assert calculate_premium_rate(10.0, 0.0) == 0.0


def test_discount_space():
    # 转股价值100，转债价格90，折价空间10
    assert calculate_discount_space(100.0, 90.0) == 10.0


def test_discount_space_negative():
    # 转股价值100，转债价格110，溢价空间-10
    assert calculate_discount_space(100.0, 110.0) == -10.0
