# Claude Ollama Continuity for Windows

A Windows-first continuity layer for **Claude Code -> Ollama -> Claude Code in the same terminal**.

```text
claude
  |
  v
Anthropic Claude Code
  |
  | StopFailure: rate/provider limit
  v
Ollama + qwen3.5, same terminal and same working directory
  |
  | Claude probe succeeds + Ollama reaches a safe Stop
  v
Original Anthropic session resumes
```

This project does **not** bypass Anthropic limits. While Anthropic is unavailable, work is performed by a local Ollama model. When a real Claude Code probe succeeds again, the supervisor returns to the original Anthropic session.

## Final architecture

Anthropic and Ollama deliberately use **separate Claude Code session IDs**. They share the same repository on disk, and the supervisor transfers recent transcript context plus git state in both directions.

This isolation is important. Reusing an Anthropic session with an Ollama model such as `qwen3.5` can leave model metadata in the session that normal Claude Code cannot restore later.

## Requirements

Windows 10/11 with:

- Claude Code installed and authenticated
- Ollama installed
- Python 3 available as `py` or `python`
- `qwen3.5` installed in Ollama, unless you set another model
- Git recommended for better handoff summaries

Ollama officially supports Claude Code through its Anthropic-compatible endpoint. Claude Code officially exposes `StopFailure`, including `rate_limit`, `billing_error`, `server_error`, and `max_output_tokens`, plus the session ID and transcript path used by this supervisor.

Official references:

- Claude Code hooks: https://code.claude.com/docs/en/hooks
- Claude Code CLI: https://docs.anthropic.com/en/docs/claude-code/cli-usage
- Ollama + Claude Code: https://docs.ollama.com/integrations/claude-code

## First install or repair

From PowerShell:

```powershell
$u="$env:TEMP\claude-continuity-updater.py"; Invoke-WebRequest "https://raw.githubusercontent.com/marianelarojas30-alt/claude-ollama-fallback-windows/main/updater.py" -OutFile $u; py $u
```

The updater resolves one exact Git commit first, downloads every runtime file from that same commit, installs it, imports the installed runtime as a verification step, then reports success.

A successful install must show:

```text
Runtime verification: OK
INSTALLED / UPDATED OK
UPDATE COMPLETE
```

Close all terminals and open a new one after installation.

## Prepare Ollama

```powershell
ollama --version
ollama pull qwen3.5
ollama list
```

The requested model must appear as `qwen3.5` or `qwen3.5:latest`.

## Verify the whole installation

```powershell
claude-continuity doctor
```

Do not rely on automatic takeover until every doctor line is `OK` and the final line says `READY`.

## Normal use

Use Claude exactly as before, from any project directory:

```powershell
cd C:\path\to\your-project
claude
```

There is no `smart-claude` command required. The global `claude.cmd` wrapper starts the supervisor, which starts the real Claude executable in the same console.

## Automatic takeover

The global Claude Code hook watches `StopFailure` for:

- `rate_limit`
- `billing_error`
- `server_error`
- `max_output_tokens`

When one occurs, the supervisor captures the original Anthropic `session_id`, transcript path, working directory and permission mode. It then starts a **new** Ollama-backed Claude Code session in the same terminal and project, with the recent Anthropic transcript and repository state in its handoff prompt.

Claude itself still starts normally even if Ollama is missing. Ollama readiness is checked only when a takeover is actually required.

## Automatic return

While Ollama is active, the supervisor sends a small isolated Claude Code probe every **120 seconds** by default.

The probe is explicitly marked so its hooks cannot overwrite the real session state.

When the probe succeeds, the supervisor waits for Ollama's next `Stop` event. Only at that safe idle boundary does it stop the Ollama child and resume the **original Anthropic session ID**, adding a handback containing the current git state and recent Ollama transcript.

Change the interval if needed:

```powershell
setx CLAUDE_CONTINUITY_PROBE_SECONDS 60
```

Open a new terminal after changing it.

## Permission behavior

By default, the Ollama fallback inherits the permission mode reported by the interrupted Claude session. This avoids silently giving the local model more privileges than Claude had.

You can explicitly override it for future terminals:

```powershell
setx CLAUDE_OLLAMA_PERMISSION_MODE acceptEdits
```

`bypassPermissions` is supported but is intentionally not the default because it allows autonomous shell/file actions without the normal approval boundary.

## Change the fallback model

```powershell
setx CLAUDE_OLLAMA_MODEL qwen3.5
```

Ollama recommends a context window of at least 64K for Claude Code workloads.

## Upgrade

After the first successful installation:

```powershell
claude-continuity update
```

Every update is pinned to one exact Git commit before any runtime file is downloaded, preventing mixed-version installs.

## Diagnostics

```powershell
claude-continuity doctor
claude-continuity version
claude-continuity sessions
```

If multiple supervised Claude sessions are open, test commands refuse to guess which one you mean.

## Exact failover test

Open Claude in the project you want to test. In a second PowerShell:

```powershell
claude-continuity sessions
```

Copy the PID for the desired project, then:

```powershell
claude-continuity simulate-limit --pid 12345
```

The Claude terminal should show `CLAUDE LIMIT DETECTED` followed by `OLLAMA ACTIVE`.

When Ollama has reached an idle prompt, simulate recovery:

```powershell
claude-continuity simulate-recovery --pid 12345
```

The return waits for a safe Ollama Stop boundary, then the same terminal should show `CLAUDE ACTIVE` again.

## Important boundaries

- Context compaction is not a provider outage. Claude Code handles that separately.
- A successful availability probe proves a small Claude request works again, not that future usage cannot hit another limit.
- File state is shared because both providers operate in the same working directory. Conversation continuity is transferred explicitly; provider session IDs remain isolated.
- The supervisor never changes global Anthropic endpoint variables. Ollama endpoint variables exist only in the Ollama child process.

## License

MIT.
