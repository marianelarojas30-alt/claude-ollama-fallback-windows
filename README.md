# Claude Ollama Fallback for Windows

A Windows-first continuity bridge for **Claude Code → Ollama**.

When a Claude Code turn ends with a supported API failure, this project captures the current repository state and recent Claude transcript, then starts a new Claude Code worker backed by Ollama in the **same working directory** so it can continue the unfinished coding task.

> This is a continuity helper, not a way to bypass Anthropic billing or usage rules. The fallback work is executed by an Ollama model on your machine (or whatever Ollama model you configure).

## What it catches

The installed Claude Code `StopFailure` hook listens for:

- `rate_limit`
- `billing_error`
- `server_error`
- `max_output_tokens`

Authentication failures are intentionally excluded by default.

## Requirements

Windows 10/11 with:

- Claude Code installed and available as `claude`
- Ollama installed and available as `ollama`
- Python 3
- Git recommended

Default Ollama model: `qwen3.5`.

## Install

Clone this repository or download it from GitHub, then:

1. Run `INSTALL_WINDOWS.bat`
2. Run `PULL_MODEL_WINDOWS.bat`
3. Run `CHECK_WINDOWS.bat`
4. Optionally run `TEST_TAKEOVER_WINDOWS.bat`

The installer **merges** the new hook into `%USERPROFILE%\.claude\settings.json` instead of replacing all existing hooks, and creates a backup when that file already exists.

## How the handoff works

```text
Claude Code
   │
   │ StopFailure: rate limit / billing / server / max output
   ▼
continuity.py hook
   │
   ├─ records cwd + recent transcript
   ├─ records git status / diff summary / recent commits
   ├─ writes a handoff bundle
   └─ starts detached continuity worker
          │
          ▼
     ollama launch claude
          │
          ▼
     Claude Code using Ollama
          │
          └─ continues in the same repository
```

A recursion guard prevents the Ollama-backed worker from triggering another fallback loop through the same hook.

## Commands

After installation, PowerShell:

```powershell
& "$env:LOCALAPPDATA\claude-ollama-continuity\bin\claude-continuity.cmd" doctor
& "$env:LOCALAPPDATA\claude-ollama-continuity\bin\claude-continuity.cmd" status
& "$env:LOCALAPPDATA\claude-ollama-continuity\bin\claude-continuity.cmd" logs
& "$env:LOCALAPPDATA\claude-ollama-continuity\bin\claude-continuity.cmd" manual "continue the unfinished task and verify the result"
```

## Change the model

```powershell
setx CLAUDE_OLLAMA_MODEL qwen3.5
```

Open a new terminal after `setx`.

## Permission modes

Default:

```text
acceptEdits
```

This is deliberate. The fallback can edit repository files but still retains more safeguards than full bypass mode.

`FULL_AUTO_ON_WINDOWS.bat` changes the fallback to Claude Code `bypassPermissions`. Use it only in a trusted and preferably isolated development environment.

Return to the safer default with:

```text
SAFER_MODE_WINDOWS.bat
```

## Logs and handoff data

On Windows the runtime state is stored under:

```text
%LOCALAPPDATA%\claude-ollama-continuity\state
```

Each takeover gets its own run directory containing:

- `handoff.json`
- `handoff.md`
- `worker.log`
- `result.json`

`handoff.json` and `handoff.md` can contain excerpts from the local Claude Code transcript. Treat the state directory as sensitive and do not publish it.

## Tests

Run:

```text
RUN_TESTS_WINDOWS.bat
```

GitHub Actions also compiles and tests the Python code on `windows-latest`.

## Important limitation

Claude Code has its own context management and compaction behavior. A full context window does **not necessarily** produce `StopFailure`. This repository automatically takes over when Claude Code emits one of the configured API failure events. It cannot guarantee that every subscription usage-limit situation will be surfaced by Claude Code as one of those events.

## Uninstall

Run:

```text
UNINSTALL_WINDOWS.bat
```

That removes this project's `StopFailure` hook and installed worker. It does not uninstall Claude Code, Ollama, Python, or Git.

## Security

Read [SECURITY.md](SECURITY.md) before enabling full-auto mode.

## License

MIT.
