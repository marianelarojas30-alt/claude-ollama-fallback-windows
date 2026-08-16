#!/usr/bin/env python3
"""Installer for Claude -> Ollama Continuity."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys

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


def existing_real_claude() -> str | None:
    config = INSTALL_DIR / "config.json"
    if config.exists():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            candidate = str(data.get("real_claude") or "")
            if candidate and pathlib.Path(candidate).exists():
                return candidate
        except Exception:
            pass
    return None


def find_real_claude() -> str:
    saved = existing_real_claude()
    if saved:
        return saved
    path_parts = []
    for part in os.environ.get("PATH", "").split(os.pathsep):
        try:
            if pathlib.Path(part).resolve() == BIN_DIR.resolve():
                continue
        except OSError:
            pass
        path_parts.append(part)
    candidate = shutil.which("claude", path=os.pathsep.join(path_parts))
    if not candidate:
        raise SystemExit("Claude Code must be installed before Claude Ollama Continuity.")
    return str(pathlib.Path(candidate).resolve())


def ensure_user_path_windows(directory: pathlib.Path) -> None:
    if os.name != "nt":
        return
    current = os.environ.get("PATH", "")
    target = str(directory)
    if not any(piece.lower() == target.lower() for piece in current.split(os.pathsep) if piece):
        os.environ["PATH"] = target + os.pathsep + current
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetEnvironmentVariable('Path','User')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        user_path = proc.stdout.strip()
        entries = [p for p in user_path.split(";") if p]
        entries = [p for p in entries if p.lower() != target.lower()]
        new_path = ";".join([target, *entries])
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "[Environment]::SetEnvironmentVariable('Path', $args[0], 'User')",
                new_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        print(f"WARNING: Could not add {target} to User PATH automatically.")


def main() -> int:
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

    real_claude = find_real_claude()
    atomic_write_json(
        INSTALL_DIR / "config.json",
        {
            "real_claude": real_claude,
            "repository": "marianelarojas30-alt/claude-ollama-fallback-windows",
        },
    )

    files = [
        "continuity.py",
        "supervisor.py",
        "supervisor_hook.py",
        "control.py",
        "install.py",
        "updater.py",
    ]
    for name in files:
        source = ROOT / name
        if source.exists():
            shutil.copy2(source, INSTALL_DIR / name)

    target = INSTALL_DIR / "continuity.py"
    supervisor = INSTALL_DIR / "supervisor.py"
    hook_target = INSTALL_DIR / "supervisor_hook.py"
    control = INSTALL_DIR / "control.py"
    updater = INSTALL_DIR / "updater.py"

    if os.name != "nt":
        for path in (target, supervisor, hook_target, control, updater):
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

    if os.name == "nt":
        continuity_launcher = BIN_DIR / "claude-continuity.cmd"
        continuity_launcher.write_text(
            f'@echo off\r\n'
            f'if /I "%~1"=="update" (\r\n  "{sys.executable}" "{updater}"\r\n  exit /b %ERRORLEVEL%\r\n)\r\n'
            f'if /I "%~1"=="simulate-limit" (\r\n  "{sys.executable}" "{control}" simulate-limit\r\n  exit /b %ERRORLEVEL%\r\n)\r\n'
            f'if /I "%~1"=="simulate-recovery" (\r\n  "{sys.executable}" "{control}" simulate-recovery\r\n  exit /b %ERRORLEVEL%\r\n)\r\n'
            f'if /I "%~1"=="supervisor-status" (\r\n  "{sys.executable}" "{control}" supervisor-status\r\n  exit /b %ERRORLEVEL%\r\n)\r\n'
            f'"{sys.executable}" "{target}" %*\r\n',
            encoding="utf-8",
        )
        smart_launcher = BIN_DIR / "smart-claude.cmd"
        smart_launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{supervisor}" --cwd "%CD%" -- %*\r\n',
            encoding="utf-8",
        )
        global_claude = BIN_DIR / "claude.cmd"
        global_claude.write_text(
            f'@echo off\r\nif "%CLAUDE_CONTINUITY_INTERNAL%"=="1" (\r\n  "{real_claude}" %*\r\n) else (\r\n  "{sys.executable}" "{supervisor}" --cwd "%CD%" -- %*\r\n)\r\n',
            encoding="utf-8",
        )
        ensure_user_path_windows(BIN_DIR)
    else:
        continuity_launcher = BIN_DIR / "claude-continuity"
        continuity_launcher.write_text(
            f'#!/bin/sh\n'
            f'case "$1" in\n'
            f'  update) exec "{sys.executable}" "{updater}" ;;\n'
            f'  simulate-limit|simulate-recovery|supervisor-status) exec "{sys.executable}" "{control}" "$1" ;;\n'
            f'esac\n'
            f'exec "{sys.executable}" "{target}" "$@"\n',
            encoding="utf-8",
        )
        continuity_launcher.chmod(0o755)
        smart_launcher = BIN_DIR / "smart-claude"
        smart_launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{supervisor}" --cwd "$PWD" -- "$@"\n',
            encoding="utf-8",
        )
        smart_launcher.chmod(0o755)
        global_claude = smart_launcher

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
    print("\nINSTALLED / UPDATED OK")
    print(f"Real Claude:      {real_claude}")
    print(f"Global wrapper:   {global_claude}")
    print(f"Supervisor:       {supervisor}")
    print(f"Settings:         {SETTINGS}")
    print("\nOpen a NEW terminal. From then on use: claude")
    print("Future upgrades: claude-continuity update")
    print("Test commands:   claude-continuity simulate-limit / simulate-recovery")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
