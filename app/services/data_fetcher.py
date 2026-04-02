"""
数据获取层 - 新浪实时 + THS转债信息
"""
import requests
import akshare as ak
from datetime import datetime
from typing import Optional

# 股票代码 → 新浪前缀
def _stock_prefix(code: str) -> str:
    """判断交易所前缀"""
    if code.startswith(('6', '5', '9')):
        return f"sh{code}"
    return f"sz{code}"


# ---- 股票价格 ----

def get_stock_price(stock_code: str) -> Optional[float]:
    """
    获取正股实时价格（新浪）
    """
    prefix = _stock_prefix(stock_code)
    try:
        r = requests.get(
            f"https://hq.sinajs.cn/list={prefix}",
            headers={"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        r.encoding = "gbk"
        text = r.text.strip()
        if "=" not in text:
            return None
        # 格式: var hq_str_sz300014="名称,开盘,当前,最高,最低,...,昨收,...,时间"
        inner = text.split('"')[1]
        parts = inner.split(",")
        if len(parts) < 10:
            return None
        # parts[3]=当前价, parts[4]=今开
        price = float(parts[3])
        if price <= 0:
            # 尝试昨收
            price = float(parts[2])
        return price if price > 0 else None
    except Exception:
        return None


# ---- 转债基础信息缓存 ----

_cb_info_cache: dict = {}  # stock_code -> {cb_code, cb_name, conversion_price}


def _load_cb_info() -> dict:
    """从THS加载全部转债基础信息，建立正股→转债映射"""
    try:
        df = ak.bond_zh_cov_info_ths()
        mapping = {}
        for _, row in df.iterrows():
            stock_code = str(row["正股代码"]).strip()
            if stock_code and stock_code != "nan":
                mapping[stock_code] = {
                    "cb_code": str(row["债券代码"]).strip(),
                    "cb_name": str(row["债券简称"]).strip(),
                    "conversion_price": float(row["转股价格"]),
                }
        return mapping
    except Exception:
        return {}


def get_cb_info_by_stock(stock_code: str) -> Optional[dict]:
    """
    根据正股代码获取对应转债信息（转债代码、名称、转股价）
    """
    if not _cb_info_cache:
        _cb_info_cache.update(_load_cb_info())
    return _cb_info_cache.get(stock_code)


# ---- 转债价格 ----

def _get_cb_price(cb_code: str) -> Optional[float]:
    """通过新浪获取转债实时价格"""
    # 转债代码以 1 开头是深圳，2开头是上海
    prefix = "sz" if cb_code.startswith("1") else "sh"
    try:
        r = requests.get(
            f"https://hq.sinajs.cn/list={prefix}{cb_code}",
            headers={"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        r.encoding = "gbk"
        text = r.text.strip()
        if "=" not in text:
            return None
        inner = text.split('"')[1]
        parts = inner.split(",")
        if len(parts) < 10:
            return None
        # parts[3]=当前价
        price = float(parts[3])
        return price if price > 0 else None
    except Exception:
        return None


def get_cb_info_by_stock_with_price(stock_code: str) -> Optional[dict]:
    """
    获取转债完整信息：代码、名称、转股价、当前价格
    """
    info = get_cb_info_by_stock(stock_code)
    if not info:
        return None
    cb_price = _get_cb_price(info["cb_code"])
    if cb_price is None:
        return None
    return {
        "cb_code": info["cb_code"],
        "cb_name": info["cb_name"],
        "cb_price": cb_price,
        "conversion_price": info["conversion_price"],
    }


# ---- 保留旧接口兼容 ----

def get_stock_info(stock_code: str) -> Optional[dict]:
    """保留，暂未使用"""
    try:
        df = ak.stock_individual_info_em(symbol=stock_code)
        return {row["item"]: row["value"] for _, row in df.iterrows()}
    except Exception:
        return None
