# Claude Ollama Fallback for Windows

A Windows-first **same-terminal continuity supervisor** for Claude Code and Ollama.

The goal is simple:

```text
Claude Code
   ↓ usage/provider limit
Ollama takes over in the SAME terminal
   ↓ Claude becomes available again
Return to Claude at a safe idle boundary
```

The supervisor preserves the same working directory and reuses the Claude Code session ID with `--resume` so the conversation can continue instead of starting over.

> This does not bypass Anthropic limits. When Claude is unavailable, the work is performed by an Ollama model. When a real Claude request succeeds again, the supervisor switches back.

## What triggers takeover

The `StopFailure` hook watches for:

- `rate_limit`
- `overloaded`
- `billing_error`
- `server_error`
- `max_output_tokens`

Authentication and invalid-request errors are intentionally excluded.

## Requirements

Windows 10/11 with:

- Claude Code available as `claude`
- Ollama available as `ollama`
- Python 3
- Git recommended

Default fallback model: `qwen3.5`.

## Install

```text
INSTALL_WINDOWS.bat
PULL_MODEL_WINDOWS.bat
CHECK_WINDOWS.bat
```

The installer merges its hooks into `%USERPROFILE%\.claude\settings.json` and backs up an existing settings file.

## Start the smart session

For automatic failover **and automatic return to Claude**, start your coding session with:

```text
START_SMART_CLAUDE_WINDOWS.bat
```

or PowerShell:

```powershell
& "$env:LOCALAPPDATA\claude-ollama-continuity\bin\smart-claude.cmd"
```

Starting ordinary `claude` does not give the supervisor control of that terminal. Use `smart-claude` when you want seamless switching.

## How automatic return works

While Ollama is active, the supervisor periodically sends a very small real request to Claude Code in an isolated probe directory.

Default probe interval: **5 minutes**.

If the probe succeeds, the supervisor does not immediately kill Ollama. It waits until the Ollama-backed Claude Code session emits `Stop`, which means the assistant has finished the current response. At that safe boundary it resumes the same session on Claude in the same terminal.

Change the interval, for example to two minutes:

```powershell
setx CLAUDE_CONTINUITY_PROBE_SECONDS 120
```

Open a new terminal after `setx`.

## Ollama connection

The fallback Claude Code child process uses Ollama's Anthropic-compatible local endpoint only for that process:

```text
ANTHROPIC_AUTH_TOKEN=ollama
ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=http://localhost:11434
```

These values are not written globally by the supervisor, which lets it return cleanly to the normal Anthropic-backed Claude Code process.

## Change the fallback model

```powershell
setx CLAUDE_OLLAMA_MODEL qwen3.5
```

For large repositories, configure an Ollama context window of 64K or higher when the model and hardware allow it.

## Permission modes

Default fallback permission mode:

```text
acceptEdits
```

`FULL_AUTO_ON_WINDOWS.bat` changes the Ollama-backed Claude Code process to `bypassPermissions`. That is intentionally not the default because it removes important command approval protections.

Return to the safer mode with:

```text
SAFER_MODE_WINDOWS.bat
```

## Hooks installed

The supervisor uses three Claude Code lifecycle events:

- `StopFailure` to detect a supported Claude API failure
- `UserPromptSubmit` to know that the Ollama fallback is actively processing a new turn
- `Stop` to identify a safe idle boundary for switching back to Claude

The hook process only writes small local control signals. The parent supervisor performs the actual provider switching.

## Diagnostics

```text
CHECK_WINDOWS.bat
RUN_TESTS_WINDOWS.bat
```

Inside Claude Code, `/hooks` can be used to verify the installed hook entries.

## Important limitation

A **subscription or provider limit** that Claude Code exposes as `StopFailure` can trigger takeover.

A **context-window compaction event** is different. Claude Code has `PreCompact` and `PostCompact` lifecycle behavior and may compact the conversation instead of producing `StopFailure`. This project does not pretend those are the same condition.

Also, automatic return is based on a successful Claude availability probe. A successful probe proves that a small Claude Code request works again, but it cannot guarantee that every later request will remain below all account or provider limits.

## Uninstall

```text
UNINSTALL_WINDOWS.bat
```

This removes this project's installed hooks and files. It does not uninstall Claude Code, Ollama, Python, or Git.

## Security

Read [SECURITY.md](SECURITY.md) before enabling full-auto mode.

## License

MIT.
