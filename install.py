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


def main() -> int:
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

    target = INSTALL_DIR / "continuity.py"
    shutil.copy2(ROOT / "continuity.py", target)
    if os.name != "nt":
        target.chmod(target.stat().st_mode | stat.S_IXUSR)

    if os.name == "nt":
        launcher = BIN_DIR / "claude-continuity.cmd"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{target}" %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = BIN_DIR / "claude-continuity"
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{target}" "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)

    data = load_settings()
    hooks = data.setdefault("hooks", {})
    stop_failure = hooks.setdefault("StopFailure", [])
    marker = str(target)
    already = any(marker in json.dumps(entry) for entry in stop_failure)
    if not already:
        stop_failure.append(
            {
                "matcher": "rate_limit|billing_error|server_error|max_output_tokens",
                "hooks": [
                    {
                        "type": "command",
                        "command": sys.executable,
                        "args": [str(target), "hook"],
                        "timeout": 10,
                    }
                ],
            }
        )

    if SETTINGS.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = SETTINGS.with_name(f"settings.json.continuity-backup-{stamp}")
        shutil.copy2(SETTINGS, backup)
        print(f"Backup: {backup}")

    atomic_write_json(SETTINGS, data)
    print("\nINSTALLED OK")
    print(f"Worker:   {target}")
    print(f"Launcher: {launcher}")
    print(f"Settings: {SETTINGS}")
    print("\nNext: install/pull an Ollama model, then run the doctor command.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
