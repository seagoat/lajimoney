@echo off
cd /d %~dp0

echo [0/4] Checking uv...
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing uv via PowerShell...
    powershell -ExecutionPolicy ByPass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri https://astral.sh/uv/install.ps1 -OutFile $env:TEMP\uv-install.ps1; powershell -ExecutionPolicy Bypass -File $env:TEMP\uv-install.ps1; Remove-Item $env:TEMP\uv-install.ps1 -Force"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>&1
    if %errorlevel% neq 0 (
        echo PowerShell install failed, trying curl...
        curl -Lo "%TEMP%\uv-installer.exe" "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc-installer.exe"
        if %errorlevel% equ 0 (
            "%TEMP%\uv-installer.exe" /S
            del "%TEMP%\uv-installer.exe"
        )
        set "PATH=%USERPROFILE%\.local\bin;%PATH%"
        where uv >nul 2>&1
        if %errorlevel% neq 0 (
            echo uv install failed.
            pause
            exit /b 1
        )
    )
    echo uv installed!
)

echo [1/4] Installing Python 3.12 via uv...
uv python install 3.12 --preview
echo Python 3.12 ready (or already installed).

echo [2/4] Setting up virtual environment...
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe -c "import sys; sys.exit(0)" >nul 2>&1
    if %errorlevel% equ 0 (
        echo Using existing venv
    ) else (
        echo Bad venv, recreating...
        rmdir /s /q .venv 2>nul
        uv venv .venv --python 3.12
    )
) else (
    echo Creating new venv...
    uv venv .venv --python 3.12
)

echo [3/4] Installing dependencies (using Tsinghua mirror)...
uv pip install -r requirements.txt --python .venv\Scripts\python.exe -i https://pypi.tuna.tsinghua.edu.cn/simple --only-binary pydantic --only-binary pydantic-core
if %errorlevel% neq 0 (
    echo Fallback: installing without binary restrictions...
    uv pip install -r requirements.txt --python .venv\Scripts\python.exe -i https://pypi.tuna.tsinghua.edu.cn/simple
    if %errorlevel% neq 0 (
        echo Dependencies install failed.
        pause
        exit /b 1
    )
)

echo.
echo [4/4] Starting server...
echo Open http://localhost:8001
echo Press Ctrl+C to stop
echo.
.venv\Scripts\python.exe run.py
if %errorlevel% neq 0 (
    echo Server exited with error.
    pause
)
