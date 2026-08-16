#!/usr/bin/env python3
"""Installer for Claude -> Ollama Continuity."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import sys
import datetime as dt

APP = "claude-ollama-continuity"
ROOT = pathlib.Path(__file__).resolve().parent
HOME = pathlib.Path.home()
CLAUDE_DIR = HOME / ".claude"
SETTINGS = CLAUDE_DIR / "settings.json"

if os.name == "nt":
    LOCAL = pathlib.Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))
    INSTALL_DIR = LOCAL / APP
    BIN_DIR = INSTALL_DIR / "bin"
else:
    INSTALL_DIR = HOME / ".local" / "share" / APP
    BIN_DIR = HOME / ".local" / "bin"


def load_settings() -> dict:
    if not SETTINGS.exists():
        return {}
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {SETTINGS}: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"{SETTINGS} root must be a JSON object")
    return data


def atomic_write_json(path: pathlib.Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _ensure_hook(hooks: dict, event: str, target: pathlib.Path, matcher: str | None = None) -> None:
    entries = hooks.setdefault(event, [])
    marker = str(target)
    if any(marker in json.dumps(entry) for entry in entries):
        return
    entry = {
        "hooks": [
            {
                "type": "command",
                "command": sys.executable,
                "args": [str(target)],
                "timeout": 10,
            }
        ]
    }
    if matcher is not None:
        entry["matcher"] = matcher
    entries.append(entry)


def main() -> int:
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

    target = INSTALL_DIR / "continuity.py"
    supervisor = INSTALL_DIR / "supervisor.py"
    hook_target = INSTALL_DIR / "supervisor_hook.py"
    shutil.copy2(ROOT / "continuity.py", target)
    shutil.copy2(ROOT / "supervisor.py", supervisor)
    shutil.copy2(ROOT / "supervisor_hook.py", hook_target)
    if os.name != "nt":
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
        supervisor.chmod(supervisor.stat().st_mode | stat.S_IXUSR)
        hook_target.chmod(hook_target.stat().st_mode | stat.S_IXUSR)

    if os.name == "nt":
        launcher = BIN_DIR / "claude-continuity.cmd"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{target}" %*\r\n',
            encoding="utf-8",
        )
        smart_launcher = BIN_DIR / "smart-claude.cmd"
        smart_launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{supervisor}" --cwd "%CD%"\r\n',
            encoding="utf-8",
        )
    else:
        launcher = BIN_DIR / "claude-continuity"
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{target}" "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        smart_launcher = BIN_DIR / "smart-claude"
        smart_launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{supervisor}" --cwd "$PWD"\n',
            encoding="utf-8",
        )
        smart_launcher.chmod(0o755)

    data = load_settings()
    hooks = data.setdefault("hooks", {})

    legacy_markers = (str(target), str(hook_target), APP)
    for event in ("StopFailure", "Stop", "UserPromptSubmit"):
        entries = hooks.get(event, [])
        hooks[event] = [
            entry for entry in entries
            if not any(marker in json.dumps(entry) for marker in legacy_markers)
        ]
        if not hooks[event]:
            hooks.pop(event, None)

    _ensure_hook(
        hooks,
        "StopFailure",
        hook_target,
        "rate_limit|overloaded|billing_error|server_error|max_output_tokens",
    )
    _ensure_hook(hooks, "Stop", hook_target)
    _ensure_hook(hooks, "UserPromptSubmit", hook_target)

    if SETTINGS.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = SETTINGS.with_name(f"settings.json.continuity-backup-{stamp}")
        shutil.copy2(SETTINGS, backup)
        print(f"Backup: {backup}")

    atomic_write_json(SETTINGS, data)
    print("\nINSTALLED OK")
    print(f"Worker:          {target}")
    print(f"Supervisor:      {supervisor}")
    print(f"Supervisor hook: {hook_target}")
    print(f"Launcher:        {launcher}")
    print(f"Smart launcher:  {smart_launcher}")
    print(f"Settings:        {SETTINGS}")
    print("\nFor same-terminal automatic failover and return, start work with smart-claude.cmd")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
