@echo off
setlocal
echo WARNING: this enables bypassPermissions for the OLLAMA FALLBACK only.
echo It can execute commands without approval. Use only in trusted repositories.
echo.
setx CLAUDE_OLLAMA_PERMISSION_MODE bypassPermissions >nul
if errorlevel 1 (
  echo Failed to set environment variable.
  pause
  exit /b 1
)
echo Enabled. Open a NEW terminal before using it.
pause
