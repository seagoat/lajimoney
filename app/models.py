from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# === 底仓模型 ===

class HoldingCreate(BaseModel):
    stock_code: str
    stock_name: str
    shares: float
    cost_price: float


class HoldingUpdate(BaseModel):
    stock_name: Optional[str] = None
    shares: Optional[float] = None
    cost_price: Optional[float] = None


class HoldingResponse(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    shares: float
    cost_price: float
    created_at: str
    updated_at: str


# === 信号模型 ===

class SignalResponse(BaseModel):
    id: int
    cb_code: str
    cb_name: Optional[str]
    stock_code: str
    stock_price: Optional[float]
    cb_price: Optional[float]
    conversion_price: Optional[float]
    conversion_value: Optional[float]
    premium_rate: Optional[float]
    discount_space: Optional[float]
    target_buy_price: Optional[float]
    target_shares: Optional[int]
    signal_time: str
    status: str


# === 成交模型 ===

class TradeResponse(BaseModel):
    id: int
    signal_id: Optional[int]
    cb_code: str
    cb_name: Optional[str]
    buy_time: Optional[str]
    buy_price: Optional[float]
    buy_shares: Optional[int]
    buy_amount: Optional[float]
    sell_time: Optional[str]
    sell_price: Optional[float]
    sell_amount: Optional[float]
    profit: Optional[float]
    profit_rate: Optional[float]
    status: str


# === 汇总模型 ===

class DailySummaryResponse(BaseModel):
    id: int
    trade_date: str
    total_signals: int
    total_executed: int
    total_profit: float
    win_rate: float


class OverviewResponse(BaseModel):
    total_profit: float
    total_trades: int
    win_rate: float
    pending_count: int
    today_signals: int


# === 设置模型 ===

class SettingsResponse(BaseModel):
    discount_threshold: float
    target_lot_size: int
    scan_mode: str  # 'holdings' | 'all'


class SettingsUpdate(BaseModel):
    discount_threshold: Optional[float] = None
    target_lot_size: Optional[int] = None
    scan_mode: Optional[str] = None
