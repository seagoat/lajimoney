@echo off
cd /d %~dp0
call .venv\Scripts\activate
uv pip install -r requirements.txt -q
python run.py
pause
