@echo off
setlocal
set "SMART=%LOCALAPPDATA%\claude-ollama-continuity\bin\smart-claude.cmd"
if not exist "%SMART%" (
  echo Claude Ollama Continuity is not installed yet.
  echo Run INSTALL_WINDOWS.bat first.
  pause
  exit /b 1
)
call "%SMART%"
endlocal
