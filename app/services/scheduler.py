"""
后台定时扫描调度器
"""
import asyncio
from datetime import datetime, time
from typing import Optional

# 最新扫描结果（供 SSE 接口读取）
latest_scan_result: Optional[dict] = None

# 扫描间隔（秒）
_scan_interval: int = 5

# 定时器是否已启动
_started: bool = False

# 扫描中的标志（防止并发）
_scan_in_progress: bool = False

# 扫描完成信号（供 SSE 等待）
_scan_done_event: asyncio.Event = asyncio.Event()

# 是否启用自动扫描
_scan_enabled: bool = True

# 定时器句柄（用于关闭时取消）
_timer_handle: Optional[asyncio.TimerHandle] = None

# 服务器关闭信号（通知 SSE 连接关闭）
_server_shutdown_event: asyncio.Event = asyncio.Event()

# 非交易时段已扫且无新信号的标记（避免重复扫描）
_non_trading_no_signal_done: bool = False

# 上一次扫描是否为交易日（用于判断是否跨日，需重置标记）
_last_scan_date: Optional[str] = None


def is_trading_time() -> bool:
    """判断当前是否为 A 股交易时段（周一至周五 9:30-11:30, 13:00-15:00）"""
    now = datetime.now()
    weekday = now.weekday()  # Mon=0, Sun=6
    if weekday >= 5:  # 周六、周日
        return False
    t = now.time()
    morning_start = time(9, 30)
    morning_end = time(11, 30)
    afternoon_start = time(13, 0)
    afternoon_end = time(15, 0)
    if morning_start <= t <= morning_end or afternoon_start <= t <= afternoon_end:
        return True
    return False


async def _do_scan():
    """执行一次扫描，结果写入 latest_scan_result"""
    global latest_scan_result, _scan_in_progress, _scan_enabled
    global _non_trading_no_signal_done, _last_scan_date

    if not _scan_enabled:
        return
    if _scan_in_progress:
        return

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    trading = is_trading_time()

    # 跨交易日重置标记
    if _last_scan_date and _last_scan_date != today:
        _non_trading_no_signal_done = False
    _last_scan_date = today

    # 非交易时段：若已完成一次扫描，跳过
    if not trading and _non_trading_no_signal_done:
        return

    _scan_in_progress = True
    _scan_done_event.clear()  # 清空上一次的完成信号

    try:
        from app.routers.signals import _run_scan, get_settings, _scan_results

        scan_id = f"auto_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        settings = await get_settings()

        # 启动扫描任务（后台运行）
        asyncio.create_task(_run_scan(scan_id, settings))

        # 等待扫描完成（最多 300 秒）
        for _ in range(300):
            await asyncio.sleep(1)
            result = _scan_results.get(scan_id)
            if result and result.get("done"):
                latest_scan_result = result
                _scan_done_event.set()

                # 非交易时段且本次无新信号 → 标记完成，后续跳过
                new_sig_count = result.get("signals_found", 0)
                if not trading and new_sig_count == 0:
                    _non_trading_no_signal_done = True
                # 有新信号则清除标记，下次继续正常扫
                elif new_sig_count > 0:
                    _non_trading_no_signal_done = False
                break
    finally:
        _scan_in_progress = False


async def _schedule_next(interval: int):
    """安排下一次扫描"""
    global _scan_interval, _timer_handle, _started
    if not _started:
        return
    _scan_interval = interval
    loop = asyncio.get_running_loop()
    _timer_handle = loop.call_later(interval, lambda: asyncio.create_task(_run_scheduler_tick()))


async def _run_scheduler_tick():
    """定时器触发时执行扫描并安排下次扫描"""
    await _do_scan()
    await _schedule_next(_scan_interval)


async def start_scheduler(interval: int = 5):
    """启动后台定时扫描"""
    global _started
    if _started:
        return
    _started = True
    await _schedule_next(interval)


async def stop_scheduler():
    """停止后台定时扫描（不取消正在进行的扫描）"""
    global _started, _timer_handle
    _started = False
    _server_shutdown_event.set()  # 通知所有 SSE 连接关闭
    if _timer_handle:
        _timer_handle.cancel()
        _timer_handle = None


def get_latest_result() -> Optional[dict]:
    """获取最新扫描结果（供 SSE 接口调用）"""
    return latest_scan_result


async def wait_for_next_scan(timeout: int = 120) -> Optional[dict]:
    """等待下一次扫描完成，返回结果（供 SSE 接口调用）"""
    import time
    waited = 0
    interval = 1.0
    while waited < timeout:
        if _server_shutdown_event.is_set():
            return None  # 服务器关闭，立即返回
        if _scan_done_event.is_set():
            _scan_done_event.clear()
            return latest_scan_result
        await asyncio.sleep(interval)
        waited += interval
    return None


def update_scheduler_config(enabled: bool, interval: int):
    """更新调度器配置（被 settings.py 调用）"""
    global _scan_enabled, _scan_interval
    _scan_enabled = enabled
    _scan_interval = interval


def get_shutdown_event() -> asyncio.Event:
    """获取服务器关闭事件，供 SSE 接口等待"""
    return _server_shutdown_event


def is_shutting_down() -> bool:
    """服务器是否正在关闭"""
    return _server_shutdown_event.is_set()
