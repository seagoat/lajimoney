# 首页定时自动扫描实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 服务端后台定时运行扫描，SSE 实时推送最新结果到前端页面，设置页可配置扫描间隔

**Architecture:**
- 后台定时器基于 `asyncio` + `asyncio.create_task`，定时触发全量扫描
- 扫描结果保存到 `app/services/scheduler.py` 的模块级变量 `latest_scan_result`
- 新增 `/api/signals/auto-scan-sse` SSE 接口，前端连接后持续接收最新扫描推送
- 扫描间隔作为 settings 中一项存储，默认 5 秒

**Tech Stack:** FastAPI, SSE (text/event-stream), asyncio

---

## File Structure

```
app/
  services/
    scheduler.py          # 新增：后台定时扫描调度器
  routers/
    signals.py            # 修改：新增 auto-scan-sse 接口
    settings.py           # 修改：支持 scan_interval 读写
  models.py               # 修改：SettingsResponse/Update 增加 scan_interval
  templates/
    settings.html         # 修改：增加扫描间隔输入框
    index.html            # 修改：连接 auto-scan-sse 实时更新结果
```

---

## Task 1: 添加 scan_interval 到 models.py 和数据库

**Files:**
- Modify: `app/models.py:104-130`
- Modify: `app/database.py`
- Modify: `app/routers/settings.py:10-29` and `32-94`

- [ ] **Step 1: 修改 SettingsResponse 和 SettingsUpdate**

在 `models.py` 的 `SettingsResponse` 和 `SettingsUpdate` 中增加 `scan_interval: int` 字段（秒）。

```python
# SettingsResponse 末尾增加
scan_interval: int = 5  # 自动扫描间隔（秒）

# SettingsUpdate 末尾增加
scan_interval: Optional[int] = None
```

- [ ] **Step 2: 修改 database.py 初始化**

在 `database.py` 的 `init_db()` 中，在 new_settings 列表里增加：

```python
('scan_interval', '5'),
```

- [ ] **Step 3: 修改 settings.py get_settings**

在 `app/routers/settings.py` 的 `get_settings()` 返回字典中增加：

```python
"scan_interval": int(settings.get("scan_interval", "5")),
```

- [ ] **Step 4: 修改 settings.py update_settings**

在 `app/routers/settings.py` 的 `update_settings()` 中，增加：

```python
if update.scan_interval is not None:
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
        ("scan_interval", str(update.scan_interval), now)
    )
```

---

## Task 2: 创建后台调度器 scheduler.py

**Files:**
- Create: `app/services/scheduler.py`

- [ ] **Step 1: 创建 scheduler.py**

```python
"""
后台定时扫描调度器
"""
import asyncio
from typing import Optional

# 最新扫描结果（供 SSE 接口读取）
latest_scan_result: Optional[dict] = None

# 定时器句柄（可取消）
_timer_handle: Optional[asyncio.TimerHandle] = None

# 扫描间隔（秒）
_scan_interval: int = 5

# 定时器是否已启动
_started: bool = False


async def _do_scan():
    """执行一次扫描，结果写入 latest_scan_result"""
    from app.routers.signals import _run_scan, get_settings
    from datetime import datetime

    global latest_scan_result

    scan_id = f"auto_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    settings = await get_settings()

    await _run_scan(scan_id, settings)
    latest_scan_result = {
        "scan_id": scan_id,
        "done": True,
        "signals_found": None,
        "signals": [],
        "all_scanned": [],
        "message": "",
    }

    # 从 _scan_results 取出结果（和手动扫描共用）
    from app.routers.signals import _scan_results
    result = _scan_results.get(scan_id)
    if result:
        latest_scan_result = result


async def _schedule_next(interval: int):
    """安排下一次扫描"""
    global _timer_handle, _started, _scan_interval
    _scan_interval = interval
    _timer_handle = asyncio.get_event_loop().call_later(interval, lambda: asyncio.create_task(_run_scheduler_tick()))


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
    """停止后台定时扫描"""
    global _timer_handle, _started
    _started = False
    if _timer_handle:
        _timer_handle.cancel()
        _timer_handle = None


def get_latest_result() -> Optional[dict]:
    """获取最新扫描结果（供 SSE 接口调用）"""
    return latest_scan_result
```

- [ ] **Step 2: 修改 main.py 启动和关闭 scheduler**

在 `app/main.py` 中：

```python
from app.services.scheduler import start_scheduler, stop_scheduler

@app.on_event("startup")
async def startup():
    await init_db()
    # 启动后台定时扫描（从数据库读取间隔）
    from app.routers.settings import get_settings
    s = await get_settings()
    await start_scheduler(s.get("scan_interval", 5))

@app.on_event("shutdown")
async def shutdown():
    from app.services.scheduler import stop_scheduler
    await stop_scheduler()
```

---

## Task 3: 新增 auto-scan-sse 接口

**Files:**
- Modify: `app/routers/signals.py`

- [ ] **Step 1: 在 signals.py 顶部添加导入**

```python
from app.services.scheduler import get_latest_result
```

- [ ] **Step 2: 新增 auto-scan-sse 接口**

在 `signals.py` 末尾添加：

```python
@router.get("/auto-scan-sse")
async def auto_scan_sse():
    """
    SSE 流：推送最新扫描结果（定时扫描触发后推送一次）
    前端打开页面时连接，收到结果后继续等待下一次推送
    """
    async def event_generator():
        from app.services.scheduler import get_latest_result, latest_scan_result
        import asyncio

        while True:
            # 等待新结果（轮询 latest_scan_result 引用变化）
            for _ in range(300):  # 最多等 300 秒
                await asyncio.sleep(1)
                result = get_latest_result()
                if result and result.get("done"):
                    yield f"event: done\ndata: {json.dumps({'signals_found': result.get('signals_found', 0), 'signals': result.get('signals', []), 'all_scanned': result.get('all_scanned', []), 'message': result.get('message', '')}, ensure_ascii=False)}\n\n"
                    break
            else:
                yield f"event: done\ndata: {json.dumps({'signals_found': 0, 'signals': [], 'all_scanned': [], 'message': '等待首次扫描'}, ensure_ascii=False)}\n\n"
                return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
```

---

## Task 4: 更新 settings.html 添加扫描间隔配置

**Files:**
- Modify: `app/templates/settings.html:4-37`

- [ ] **Step 1: 在"扫描参数"区域增加扫描间隔输入框**

在 `settings.html` 的"扫描参数"表单里，`scan_mode` select 之后添加：

```html
<div class="form-group">
    <label>自动扫描间隔（秒）</label>
    <input type="number" name="scan_interval" id="scan_interval"
           min="1" max="300" value="5" required>
    <small style="color:#888;display:block;margin-top:4px;">
        服务端后台自动扫描的间隔，默认 5 秒（1-300 秒）
    </small>
</div>
```

- [ ] **Step 2: 修改 loadSettings 的 JS**

在 `settings.html` 的 `loadSettings()` 函数中，添加：

```javascript
document.getElementById('scan_interval').value = s.scan_interval || 5;
```

- [ ] **Step 3: 修改提交表单的 body**

在 `settingsForm.onsubmit` 的 `body` 对象中，添加：

```javascript
scan_interval: parseInt(form.get('scan_interval') || '5'),
```

---

## Task 5: 更新 index.html 连接 SSE 实时刷新

**Files:**
- Modify: `app/templates/index.html:50-468`

- [ ] **Step 1: 添加 autoScan SSE 连接函数**

在 `<script>` 标签顶部添加：

```javascript
let autoScanSource = null;

function connectAutoScan() {
    if (autoScanSource) {
        autoScanSource.close();
    }
    autoScanSource = new EventSource('/api/signals/auto-scan-sse');

    autoScanSource.addEventListener('done', function(e) {
        const data = JSON.parse(e.data);
        // 收到最新结果，自动刷新扫描结果区域
        if (data.all_scanned && data.all_scanned.length > 0) {
            // 复用现有的 triggerScan 结果渲染逻辑
            renderScanResult(data);
        }
    });

    autoScanSource.onerror = function() {
        // 连接断开时静默重连
        autoScanSource.close();
        setTimeout(connectAutoScan, 5000);
    };
}

function renderScanResult(data) {
    // 将 data.all_scanned 渲染到扫描结果区域
    // 复用 triggerScan() 中 done 事件的渲染逻辑
    const resultDiv = document.getElementById('scanResult') || createResultDiv();
    // ... 同 triggerScan 的 done 处理逻辑
}
```

- [ ] **Step 2: 页面加载时连接 SSE**

在 `loadCurrentSettings()` 调用后添加：

```javascript
connectAutoScan();
```

---

## Task 6: 提交代码

- [ ] **Step 1: 提交所有更改**

```bash
git add app/models.py app/database.py app/routers/settings.py app/services/scheduler.py app/routers/signals.py app/main.py app/templates/settings.html app/templates/index.html
git commit -m "feat: add auto-scan with SSE real-time push and configurable interval"
```
