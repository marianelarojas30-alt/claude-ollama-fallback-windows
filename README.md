# Claude Ollama Continuity for Windows

A Windows-first continuity layer for **Claude Code -> Ollama -> Claude Code in the same terminal**.

```text
claude
  |
  v
Anthropic Claude Code, original session
  |
  | StopFailure: rate/provider failure
  v
Ollama + qwen3.5, separate session, same terminal and working directory
  |
  | safe Stop + retry interval
  v
Resume the original Anthropic session
  |
  | if Anthropic is still limited, StopFailure fires again
  v
Ollama takes over again
```

This project does not bypass Anthropic limits. While Anthropic is unavailable, work is performed by Ollama.

## Why the providers use separate sessions

Anthropic and Ollama deliberately use separate Claude Code session IDs. They share the same repository on disk. Recent transcript context and repository state are transferred in handoff prompts.

This prevents an Ollama model name such as `qwen3.5` from being stored in the original Anthropic session metadata.

## Requirements

Windows 10/11 with:

- Claude Code installed and authenticated
- Ollama installed and running
- Python 3 available as `py` or `python`
- `qwen3.5` installed in Ollama, unless another model is configured
- Git recommended for richer repository handoffs

Official references:

- Claude Code StopFailure hooks: https://code.claude.com/docs/en/hooks
- Claude Code authentication and programmatic usage: https://code.claude.com/docs/en/authentication
- Ollama + Claude Code: https://docs.ollama.com/integrations/claude-code

## Install or repair

Run this once in PowerShell:

```powershell
$u="$env:TEMP\claude-continuity-updater.py"; Invoke-WebRequest "https://raw.githubusercontent.com/marianelarojas30-alt/claude-ollama-fallback-windows/main/updater.py?cb=$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())" -OutFile $u; py $u
```

The updater resolves one exact Git commit first and downloads every runtime file from that same commit. A valid install must print:

```text
Runtime verification: OK
INSTALLED / UPDATED OK
UPDATE COMPLETE
Installed commit: ...
```

Close all terminals and open a new PowerShell after installation.

## Prepare Ollama

```powershell
ollama --version
ollama pull qwen3.5
ollama list
```

Ollama documents `qwen3.5` as a supported Claude Code model. Claude Code workloads need a large context window; Ollama recommends at least 64K when hardware and model allow it.

## Verify before relying on failover

First run static diagnostics:

```powershell
claude-continuity doctor
```

Then run the real local integration smoke test:

```powershell
claude-continuity self-test
```

`self-test` checks two critical paths:

1. A synthetic Claude Code `StopFailure` produces the exact fallback signal used by the supervisor.
2. The real installed Claude Code executable completes a request through the local Ollama Anthropic-compatible endpoint with the configured fallback model.

A successful result ends with:

```text
SELF-TEST PASS: the local takeover path is operational.
```

This proves the local handoff path. It cannot manufacture a real Anthropic quota exhaustion; that part can only be observed when Anthropic actually emits `StopFailure`.

## Normal use

From any trusted project directory:

```powershell
cd C:\path\to\your-project
claude
```

No `smart-claude` command is needed. The global `claude.cmd` wrapper starts the supervisor and the real Claude Code process in the same console.

## Automatic takeover

Claude Code officially fires `StopFailure` instead of `Stop` when a turn ends because of an API error. This project switches to Ollama for these supported errors:

- `rate_limit`
- `billing_error`
- `server_error`
- `max_output_tokens`

The hook captures the original Anthropic session ID, transcript path, working directory and permission mode. The supervisor then launches a new Ollama-backed Claude Code session in the same terminal and project.

Claude still opens normally even if Ollama is unavailable. Ollama is validated only when a takeover is required.

## Automatic return without a false quota probe

Older versions of this repository used `claude -p` to test whether Claude had become available again. That is not reliable for subscription quota recovery: current Claude Code documentation states that `claude -p` / Agent SDK usage can draw from a separate monthly Agent SDK credit from interactive usage.

The current design therefore does **not** use `claude -p` to decide when interactive Claude is back.

Instead:

1. Ollama continues working.
2. The supervisor waits for an Ollama `Stop`, a safe idle boundary.
3. After the retry interval, it stops the Ollama child and resumes the **original interactive Anthropic session** with `--resume` plus a handback summary.
4. That real interactive resume is the availability test.
5. If Anthropic is still limited, its real `StopFailure` fires and the supervisor immediately hands control back to Ollama again.

Default retry interval: five minutes.

Change it for future terminals with:

```powershell
setx CLAUDE_CONTINUITY_RETRY_SECONDS 300
```

## Permission behavior

By default, the Ollama fallback inherits the permission mode reported by the interrupted Claude session. This prevents silently giving the fallback more privileges than the original session.

An explicit override can be set for future terminals:

```powershell
setx CLAUDE_OLLAMA_PERMISSION_MODE acceptEdits
```

`bypassPermissions` is supported but intentionally not the default.

## Change the fallback model

```powershell
setx CLAUDE_OLLAMA_MODEL qwen3.5
```

## Upgrade

After a successful installation:

```powershell
claude-continuity update
```

Updates are pinned to one exact Git commit before runtime files are downloaded.

## Diagnostics

```powershell
claude-continuity doctor
claude-continuity self-test
claude-continuity version
claude-continuity sessions
```

If multiple supervised sessions are running, test commands refuse to guess which one to target.

## Manual failover simulation

This is optional. Open Claude in the target project. In a second PowerShell:

```powershell
claude-continuity sessions
```

Use the displayed PID:

```powershell
claude-continuity simulate-limit --pid 12345
```

The target terminal should show `CLAUDE LIMIT DETECTED` and then `OLLAMA ACTIVE`.

After Ollama reaches an idle prompt, request an immediate safe retry of the real Anthropic session:

```powershell
claude-continuity simulate-recovery --pid 12345
```

This does not claim that Anthropic is available. It only requests a real interactive retry at the next safe Ollama Stop. If Anthropic is still limited, the supervisor returns to Ollama again.

## Boundaries

- Context compaction is not a provider outage and does not trigger this fallback.
- File state is shared because both providers operate in the same working directory.
- Provider session IDs stay separate.
- The supervisor does not set the Ollama Anthropic endpoint globally; those environment variables exist only in the Ollama child process.
- A green CI run and `SELF-TEST PASS` validate the software path, but a real account quota event can only be proven against a real `StopFailure` from Anthropic.

## License

MIT.
