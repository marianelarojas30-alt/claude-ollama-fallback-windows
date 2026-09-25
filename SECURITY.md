# Security

This project launches coding agents that can read and modify files in the current working directory.

- The Ollama fallback inherits the interrupted Claude session's permission mode by default. It does not silently grant itself broader permissions.
- You may override the fallback permission mode with `CLAUDE_OLLAMA_PERMISSION_MODE`, but `bypassPermissions` removes normal approval boundaries and should only be used in an isolated environment you trust.
- The handoff prompt explicitly tells the fallback not to expose secrets or perform remote, destructive, publishing, deployment, or account-level actions unless the original task explicitly required them.
- Anthropic and Ollama use separate Claude Code sessions. They share repository files on disk, but model/session metadata is not reused across providers.
- Recent transcript excerpts may be read locally to build provider handoffs. Treat Claude Code transcripts and `%LOCALAPPDATA%\claude-ollama-continuity\state` as sensitive.
- The availability probe runs in an isolated directory and is marked so continuity hooks ignore it.
- Installation merges only the three required user hooks into `~/.claude/settings.json` and creates a timestamped backup first.
- Run `claude-continuity doctor` after upgrades and before relying on automatic takeover.

To report a security problem, open a GitHub issue without including secrets, credentials, private source code, or private logs.


## Host and Network Boundary

- This project is installed and run by each user on their own computer. The maintainer's machine is not a backend, relay, runner, or service for users.
- The Ollama fallback endpoint defaults to localhost only.
- Do not expose Ollama or continuity control state to a LAN or the public Internet by default.
- Do not execute bootstrap code directly from a mutable branch URL. Clone/download first, inspect, then run the updater.
- Repository text, issue content, transcripts, model output, and fetched content are untrusted data and must never override secret-handling or permission boundaries.
