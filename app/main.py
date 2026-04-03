from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from app.database import init_db
from app.routers import holdings, signals, trades, summary, settings, margin

app = FastAPI(title="可转债套利系统")

app.include_router(holdings.router)
app.include_router(signals.router)
app.include_router(trades.router)
app.include_router(summary.router)
app.include_router(settings.router)
app.include_router(margin.router)

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


@app.get("/trades", response_class=HTMLResponse)
async def trades_page():
    return render_template("trades.html")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    return render_template("settings.html")


@app.on_event("startup")
async def startup():
    await init_db()
