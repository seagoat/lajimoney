"""
后台定时扫描调度器
"""
import asyncio
from typing import Optional

# 最新扫描结果（供 SSE 接口读取）
latest_scan_result: Optional[dict] = None

# 扫描间隔（秒）
_scan_interval: int = 5

# 定时器是否已启动
_started: bool = False

# 扫描中的标志（防止并发）
_scan_in_progress: bool = False


async def _do_scan():
    """执行一次扫描，结果写入 latest_scan_result"""
    global latest_scan_result, _scan_in_progress
    if _scan_in_progress:
        return
    _scan_in_progress = True

    try:
        from app.routers.signals import _run_scan, get_settings, _scan_results
        from datetime import datetime
        import asyncio

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
                break
    finally:
        _scan_in_progress = False


async def _schedule_next(interval: int):
    """安排下一次扫描"""
    global _scan_interval
    _scan_interval = interval
    loop = asyncio.get_running_loop()
    loop.call_later(interval, lambda: asyncio.create_task(_run_scheduler_tick()))


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
    global _started
    _started = False


def get_latest_result() -> Optional[dict]:
    """获取最新扫描结果（供 SSE 接口调用）"""
    return latest_scan_result
