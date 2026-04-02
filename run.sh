#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "[1/4] Checking uv..."
if ! command -v uv &> /dev/null; then
    echo "uv not found, installing..."
    pip install uv
    echo "uv installed"
fi

echo "[2/4] Setting up virtual environment..."
if [ ! -d ".venv" ]; then
    uv venv .venv
    echo "venv created"
else
    echo "Using existing venv"
fi

echo "[3/4] Installing dependencies..."
source .venv/bin/activate
uv pip install -r requirements.txt -q

echo "[4/4] Starting server..."
echo ""
echo "Open http://localhost:8001"
echo "Press Ctrl+C to stop"
echo ""
python run.py
