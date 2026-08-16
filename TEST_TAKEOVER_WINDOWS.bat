@echo off
setlocal
set "CLI=%LOCALAPPDATA%\claude-ollama-continuity\bin\claude-continuity.cmd"
if not exist "%CLI%" (
  echo ERROR: Run INSTALL_WINDOWS.bat first.
  pause
  exit /b 2
)
call "%CLI%" manual "Inspect this repository and verify the Ollama continuity takeover. Do not make destructive changes, do not publish, and do not push."
echo.
echo The fallback worker was started. Wait for it to finish, then run STATUS_WINDOWS.bat.
pause
