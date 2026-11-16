@echo off
setlocal
cd /d "%~dp0"
echo ==============================================
echo  Claude Ollama Continuity 1.0 - Windows Setup
echo ==============================================
echo.
set "PYTHON_RUNNER=py -3"
where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python 3 was not found in PATH.
    pause
    exit /b 2
  )
  set "PYTHON_RUNNER=python"
)
%PYTHON_RUNNER% install.py
set "INSTALL_RC=%errorlevel%"
if not %INSTALL_RC%==0 (
  echo.
  echo Installation failed. Copy the error above.
  pause
  exit /b %INSTALL_RC%
)
echo.
echo Installation complete.
echo Close all terminals, open a new PowerShell, then run:
echo   ollama pull qwen3.5
echo   claude-continuity doctor
echo Normal use after READY: claude
pause
exit /b 0
