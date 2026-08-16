#!/usr/bin/env python3
"""Remove Claude Ollama Continuity without uninstalling Claude Code or Ollama."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

APP = "claude-ollama-continuity"
HOME = pathlib.Path.home()
SETTINGS = HOME / ".claude" / "settings.json"

if os.name == "nt":
    LOCAL = pathlib.Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))
    INSTALL_DIR = LOCAL / APP
    BIN_DIR = INSTALL_DIR / "bin"
else:
    INSTALL_DIR = HOME / ".local" / "share" / APP
    BIN_DIR = HOME / ".local" / "bin"


def remove_hooks() -> None:
    if not SETTINGS.exists():
        return
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return
    hooks = data.get("hooks", {})
    for event in ("StopFailure", "Stop", "UserPromptSubmit"):
        entries = hooks.get(event, [])
        filtered = [entry for entry in entries if APP not in json.dumps(entry) and "supervisor_hook.py" not in json.dumps(entry)]
        if filtered:
            hooks[event] = filtered
        else:
            hooks.pop(event, None)
    SETTINGS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def remove_windows_path() -> None:
    if os.name != "nt":
        return
    target = str(BIN_DIR)
    script = (
        "$target=$args[0];"
        "$p=[Environment]::GetEnvironmentVariable('Path','User');"
        "$parts=@($p -split ';' | Where-Object {$_ -and $_.TrimEnd('\\') -ine $target.TrimEnd('\\')});"
        "[Environment]::SetEnvironmentVariable('Path',($parts -join ';'),'User')"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script, target],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def main() -> int:
    remove_hooks()
    remove_windows_path()
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR)
    print("Claude Ollama Continuity removed. Open a new terminal before using Claude Code again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
