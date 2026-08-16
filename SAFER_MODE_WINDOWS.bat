@echo off
setlocal
setx CLAUDE_OLLAMA_PERMISSION_MODE acceptEdits >nul
if errorlevel 1 (
  echo Failed to set environment variable.
  pause
  exit /b 1
)
echo Safer fallback mode enabled. Open a NEW terminal before using it.
pause
