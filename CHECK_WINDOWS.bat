@echo off
setlocal
set "CLI=%LOCALAPPDATA%\claude-ollama-continuity\bin\claude-continuity.cmd"
if not exist "%CLI%" (
  echo ERROR: Continuity is not installed. Run INSTALL_WINDOWS.bat first.
  pause
  exit /b 2
)
call "%CLI%" doctor
echo.
pause
