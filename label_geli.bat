@echo off
cd /d "%~dp0"
echo ==============================
echo   精灵标注工具 - geli (hepingge + juhuali)
echo ==============================
uv run python scripts/label_tool.py datasets\geli\images
pause
