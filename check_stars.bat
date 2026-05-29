@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo RocoPilot Stars:
gh repo view --json stargazerCount --jq ".stargazerCount"
pause
