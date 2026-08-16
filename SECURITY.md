# Security

This project launches a coding agent that can read and modify files in the current working directory.

- Default fallback permission mode is `acceptEdits`.
- `FULL_AUTO_ON_WINDOWS.bat` switches the fallback to `bypassPermissions`. That is intentionally **not** the default.
- Use full-auto mode only inside repositories you trust and preferably inside a VM, sandbox, container, or disposable development environment.
- The handoff prompt explicitly forbids exposing secrets and performing remote/destructive actions unless the original task required them.
- Handoff files are stored locally and may contain recent Claude Code transcript text. Treat `%LOCALAPPDATA%\claude-ollama-continuity\state` as sensitive and do not commit or share it.
- Review `.claude/settings.json` after installation if you already use custom hooks.

To report a security problem, open a GitHub issue without including secrets, tokens, credentials, or private logs.
