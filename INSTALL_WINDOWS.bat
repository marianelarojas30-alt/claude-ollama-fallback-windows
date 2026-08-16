@echo off
setlocal
cd /d "%~dp0"
echo ==============================================
echo  Claude to Ollama Continuity - Windows Setup
echo ==============================================
echo.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 install.py
  set INSTALL_RC=%errorlevel%
) else (
  where python >nul 2>nul
  if not %errorlevel%==0 (
    echo ERROR: Python 3 was not found in PATH.
    echo Install Python 3, reopen this window, and run this file again.
    pause
    exit /b 2
  )
  python install.py
  set INSTALL_RC=%errorlevel%
)
if not %INSTALL_RC%==0 (
  echo.
  echo Installation failed. Copy the error above.
  pause
  exit /b %INSTALL_RC%
)
echo.
echo Installation complete.
echo Next run PULL_MODEL_WINDOWS.bat and then CHECK_WINDOWS.bat.
pause
