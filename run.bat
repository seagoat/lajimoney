@echo off
cd /d %~dp0

echo [1/4] Checking uv...
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo uv not found, installing via pip...
    pip install uv
    if %errorlevel% neq 0 (
        echo uv install failed. Run: pip install uv
        pause
        exit /b 1
    )
)

echo [2/4] Setting up virtual environment...
if exist .venv\Scripts\activate.bat (
    echo Using existing venv
) else (
    echo Creating new venv...
    uv venv .venv
)

echo [3/4] Installing dependencies...
call .venv\Scripts\activate.bat
uv pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo Dependencies install failed
    pause
    exit /b 1
)

echo [4/4] Starting server...
echo.
echo Open http://localhost:8001
echo Press Ctrl+C to stop
echo.
python run.py
