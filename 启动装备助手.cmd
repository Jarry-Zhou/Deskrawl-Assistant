@echo off
setlocal
cd /d "%~dp0"
rem Reuse installed assistant settings when present; preserve explicit overrides.
if not defined DESKRAWL_ASSISTANT_DATA_DIR (
  if exist "%LOCALAPPDATA%\Deskrawl装备助手\config\lock-rules.json" (
    set "DESKRAWL_ASSISTANT_DATA_DIR=%LOCALAPPDATA%\Deskrawl装备助手"
  )
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo Missing runtime: .venv\Scripts\pythonw.exe
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "run_assistant.pyw"
