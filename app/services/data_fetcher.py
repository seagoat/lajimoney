"""
数据获取层 - 新浪实时 + THS转债信息
"""
import requests
import akshare as ak
from datetime import datetime
from typing import Optional

# 股票代码 → 新浪前缀
def _stock_prefix(code: str) -> str:
    if code.startswith(('6', '5', '9')):
        return f"sh{code}"
    return f"sz{code}"


# ---- 股票价格（支持批量） ----

def get_stock_price(stock_code: str) -> Optional[float]:
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
        inner = text.split('"')[1]
        parts = inner.split(",")
        if len(parts) < 10:
            return None
        price = float(parts[3])
        if price <= 0:
            price = float(parts[2])
        return price if price > 0 else None
    except Exception:
        return None


def _get_bulk_prices(stock_codes: list[str]) -> dict[str, float]:
    """
    批量获取股票价格（新浪，每请求最多50个代码）
    返回 {code: price}
    """
    results = {}
    for i in range(0, len(stock_codes), 50):
        batch = stock_codes[i:i + 50]
        prefixes = [_stock_prefix(c) for c in batch]
        codes_str = ",".join(prefixes)
        try:
            r = requests.get(
                f"https://hq.sinajs.cn/list={codes_str}",
                headers={"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            r.encoding = "gbk"
            for code, prefix in zip(batch, prefixes):
                try:
                    var_name = f"hq_str_{prefix}"
                    start = r.text.find(var_name)
                    if start == -1:
                        continue
                    # 开引号在 var_name 之后（var_name末尾是=），闭引号在下一个 "
                    open_quote = start + len(var_name) + 1
                    close_quote = r.text.find('"', open_quote + 1)
                    if close_quote == -1:
                        continue
                    inner = r.text[open_quote:close_quote]
                    parts = inner.split(",")
                    if len(parts) < 10:
                        continue
                    price = float(parts[3])
                    if price <= 0:
                        price = float(parts[2])
                    if price > 0:
                        results[code] = price
                except Exception:
                    continue
        except Exception:
            continue
    return results


# ---- 转债基础信息缓存 ----

_cb_info_cache: dict = {}  # stock_code -> {cb_code, cb_name, conversion_price}
_cb_list_cache: list[dict] = []  # 全量转债列表 [{stock_code, cb_code, cb_name, conversion_price}, ...]


def _load_cb_info() -> dict:
    """从THS加载全部转债基础信息，带重试"""
    import time
    last_err = None
    for attempt in range(3):
        try:
            df = ak.bond_zh_cov_info_ths()
            if df is not None and len(df) > 0:
                mapping = {}
                cb_list = []
                for _, row in df.iterrows():
                    stock_code = str(row["正股代码"]).strip()
                    if stock_code and stock_code != "nan":
                        cb_code = str(row["债券代码"]).strip()
                        mapping[stock_code] = {
                            "cb_code": cb_code,
                            "cb_name": str(row["债券简称"]).strip(),
                            "conversion_price": float(row["转股价格"]),
                        }
                        cb_list.append({
                            "stock_code": stock_code,
                            "cb_code": cb_code,
                            "cb_name": str(row["债券简称"]).strip(),
                            "conversion_price": float(row["转股价格"]),
                        })
                _cb_list_cache.clear()
                _cb_list_cache.extend(cb_list)
                return mapping
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(1)
    # 全部重试失败
    import logging
    logging.getLogger(__name__).warning(f"THS load failed after 3 attempts: {last_err}")
    return {}


def get_cb_info_by_stock(stock_code: str) -> Optional[dict]:
    if not _cb_info_cache:
        _cb_info_cache.update(_load_cb_info())
    return _cb_info_cache.get(stock_code)


# ---- 转债价格 ----

def _get_cb_price(cb_code: str) -> Optional[float]:
    prefix = "sz" if cb_code.startswith("1") else "sh"
    try:
        r = requests.get(
            f"https://hq.sinajs.cn/list={prefix}{cb_code}",
            headers={"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        r.encoding = "gbk"
        text = r.text.strip()
        var_name = f"hq_str_{prefix}{cb_code}"
        start = text.find(var_name)
        if start == -1:
            return None
        open_quote = start + len(var_name) + 1
        close_quote = text.find('"', open_quote + 1)
        if close_quote == -1:
            return None
        inner = text[open_quote:close_quote]
        parts = inner.split(",")
        if len(parts) < 4:
            return None
        price = float(parts[3])
        return price if price > 0 else None
    except Exception:
        return None


def get_cb_info_by_stock_with_price(stock_code: str) -> Optional[dict]:
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


# ---- 全量转债扫描（all模式） ----

def _get_bulk_cb_prices(cb_codes: list[str]) -> dict[str, float]:
    """
    批量获取转债价格（新浪，每请求最多50个代码）
    返回 {cb_code: price}
    """
    results = {}

    def _cb_prefix(code: str) -> str:
        return f"sz{code}" if code.startswith("1") else f"sh{code}"

    for i in range(0, len(cb_codes), 50):
        batch = cb_codes[i:i + 50]
        prefixes = [_cb_prefix(c) for c in batch]
        codes_str = ",".join(prefixes)
        try:
            r = requests.get(
                f"https://hq.sinajs.cn/list={codes_str}",
                headers={"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            r.encoding = "gbk"
            for code, prefix in zip(batch, prefixes):
                try:
                    var_name = f"hq_str_{prefix}"
                    start = r.text.find(var_name)
                    if start == -1:
                        continue
                    open_quote = start + len(var_name) + 1
                    close_quote = r.text.find('"', open_quote + 1)
                    if close_quote == -1:
                        continue
                    inner = r.text[open_quote:close_quote]
                    parts = inner.split(",")
                    if len(parts) < 4:
                        continue
                    price = float(parts[3])
                    if price > 0:
                        results[code] = price
                except Exception:
                    continue
        except Exception:
            continue
    return results


def get_all_cb_with_prices() -> list[dict]:
    """
    获取全量转债及其正股价格
    返回 [{stock_code, cb_code, cb_name, stock_price, cb_price, conversion_price}, ...]
    """
    if not _cb_list_cache:
        _load_cb_info()

    # 收集所有正股代码和转债代码
    all_stock_codes = list({c["stock_code"] for c in _cb_list_cache})
    all_cb_codes = [c["cb_code"] for c in _cb_list_cache]

    # 批量获取正股价格和转债价格
    stock_prices = _get_bulk_prices(all_stock_codes)
    cb_prices = _get_bulk_cb_prices(all_cb_codes)

    results = []
    for cb in _cb_list_cache:
        stock_code = cb["stock_code"]
        stock_price = stock_prices.get(stock_code)
        if stock_price is None:
            continue
        cb_price = cb_prices.get(cb["cb_code"])
        if cb_price is None:
            continue
        results.append({
            "stock_code": stock_code,
            "cb_code": cb["cb_code"],
            "cb_name": cb["cb_name"],
            "stock_price": stock_price,
            "cb_price": cb_price,
            "conversion_price": cb["conversion_price"],
        })
    return results


# ---- 保留旧接口 ----

def get_stock_info(stock_code: str) -> Optional[dict]:
    try:
        df = ak.stock_individual_info_em(symbol=stock_code)
        return {row["item"]: row["value"] for _, row in df.iterrows()}
    except Exception:
        return None
