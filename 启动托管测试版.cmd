@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "DESKRAWL_ASSISTANT_DATA_DIR=%LOCALAPPDATA%\Deskrawl装备助手"
if not exist ".build-venv\Scripts\pythonw.exe" (
  echo Missing test runtime: .build-venv\Scripts\pythonw.exe
  pause
  exit /b 1
)
start "" ".build-venv\Scripts\pythonw.exe" "run_assistant.pyw" --test-managed
