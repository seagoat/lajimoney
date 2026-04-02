"""
akshare 数据获取封装
"""
import akshare as ak
from datetime import datetime
from typing import Optional

# 缓存：code -> (timestamp, data)
_price_cache: dict = {}


def _get_cached(code: str, key: str, ttl: int = 60):
    """简单内存缓存"""
    cache_key = f"{code}:{key}"
    if cache_key in _price_cache:
        ts, val = _price_cache[cache_key]
        if datetime.now().timestamp() - ts < ttl:
            return val
    return None


def _set_cached(code: str, key: str, value):
    cache_key = f"{code}:{key}"
    _price_cache[cache_key] = (datetime.now().timestamp(), value)


def get_stock_price(stock_code: str) -> Optional[float]:
    """
    获取正股实时价格
    stock_code: 如 '000001' 或 '600519'
    """
    cached = _get_cached(stock_code, "price")
    if cached is not None:
        return cached

    try:
        # 东方财富实时行情
        df = ak.stock_zh_a_spot_em()
        row = df[df['代码'] == stock_code]
        if row.empty:
            return None
        price = float(row['最新价'].values[0])
        _set_cached(stock_code, "price", price)
        return price
    except Exception:
        return None


def get_cb_info_by_stock(stock_code: str) -> Optional[dict]:
    """
    根据正股代码获取对应转债信息
    返回: {cb_code, cb_name, cb_price, conversion_price} 或 None
    """
    try:
        # 获取所有可转债实时行情
        df = ak.bond_zh_hs_cov()
        # 找到正股代码匹配的行
        row = df[df['正股代码'] == stock_code]
        if row.empty:
            return None
        return {
            'cb_code': str(row['债券代码'].values[0]),
            'cb_name': str(row['债券简称'].values[0]),
            'cb_price': float(row['转债最新价'].values[0]),
            'conversion_price': float(row['转股价'].values[0]),
        }
    except Exception:
        return None


def get_stock_info(stock_code: str) -> Optional[dict]:
    """
    获取正股基本信息（名称等）
    """
    try:
        df = ak.stock_individual_info_em(symbol=stock_code)
        info = {row['item']: row['value'] for _, row in df.iterrows()}
        return info
    except Exception:
        return None
