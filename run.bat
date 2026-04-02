@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

cd /d %~dp0

echo [1/4] 检查 uv 环境...
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo uv 未找到，正在安装...
    pip install uv >nul 2>&1
    if %errorlevel% neq 0 (
        echo uv 安装失败，请手动运行: pip install uv
        pause
        exit /b 1
    )
    echo uv 安装完成
)

echo [2/4] 检查虚拟环境...
if exist .venv\Scripts\activate.bat (
    echo 使用现有虚拟环境
) else (
    echo 创建虚拟环境...
    uv venv .venv
    echo 虚拟环境创建完成
)

echo [3/4] 安装依赖...
.venv\Scripts\activate.bat
uv pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo 依赖安装失败
    pause
    exit /b 1
)

echo [4/4] 启动服务...
echo.
echo 访问 http://localhost:8001
echo 按 Ctrl+C 停止服务
echo.
python run.py
