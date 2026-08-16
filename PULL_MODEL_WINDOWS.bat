@echo off
setlocal
echo Pulling qwen3.5 with Ollama...
where ollama >nul 2>nul
if errorlevel 1 (
  echo ERROR: Ollama was not found in PATH.
  echo Install Ollama for Windows, reopen this window, then run again.
  pause
  exit /b 2
)
ollama pull qwen3.5
if errorlevel 1 (
  echo.
  echo Model download failed. Make sure Ollama is running and there is enough disk space.
  pause
  exit /b 1
)
echo.
echo Model ready.
pause
