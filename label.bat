@echo off
cd /d "%~dp0"
echo ==============================
echo   精灵标注工具
echo   默认标注: huolong
echo   如需标注其他精灵，修改此bat中的名称
echo ==============================
uv run python scripts/label_tool.py datasets\huolong
pause
