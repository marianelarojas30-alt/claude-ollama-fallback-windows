@echo off
setlocal
set "CLI=%LOCALAPPDATA%\claude-ollama-continuity\bin\claude-continuity.cmd"
if not exist "%CLI%" (
  echo ERROR: Run INSTALL_WINDOWS.bat first.
  pause
  exit /b 2
)
call "%CLI%" logs
echo.
pause
