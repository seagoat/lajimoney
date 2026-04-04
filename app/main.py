from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from app.database import init_db
from app.routers import holdings, signals, summary, settings

app = FastAPI(title="可转债套利系统")

app.include_router(holdings.router)
app.include_router(signals.router)
app.include_router(summary.router)
app.include_router(settings.router)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"


def render_template(name: str, **kwargs):
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template = env.get_template(name)
    return template.render(**kwargs)


@app.get("/", response_class=HTMLResponse)
async def index():
    from app.routers.summary import get_overview
    overview = await get_overview()
    return render_template("index.html", overview=overview)


@app.get("/holdings", response_class=HTMLResponse)
async def holdings_page():
    return render_template("holdings.html")


@app.get("/signals", response_class=HTMLResponse)
async def signals_page():
    return render_template("signals.html")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    return render_template("settings.html")


@app.on_event("startup")
async def startup():
    await init_db()
    # 启动后台定时扫描（从数据库读取间隔）
    from app.routers.settings import get_settings
    s = await get_settings()
    from app.services.scheduler import start_scheduler
    await start_scheduler(s.get("scan_interval", 5))


@app.on_event("shutdown")
async def shutdown():
    from app.services.scheduler import stop_scheduler
    await stop_scheduler()
