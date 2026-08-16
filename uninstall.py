#!/usr/bin/env python3
"""Remove the Claude -> Ollama Continuity hook and installed files."""
from __future__ import annotations

import json
import os
import pathlib
import shutil

APP = "claude-ollama-continuity"
HOME = pathlib.Path.home()
SETTINGS = HOME / ".claude" / "settings.json"

if os.name == "nt":
    LOCAL = pathlib.Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))
    INSTALL_DIR = LOCAL / APP
else:
    INSTALL_DIR = HOME / ".local" / "share" / APP


def main() -> int:
    if SETTINGS.exists():
        data = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
        hooks = data.get("hooks", {})
        entries = hooks.get("StopFailure", [])
        filtered = [entry for entry in entries if APP not in json.dumps(entry)]
        if filtered:
            hooks["StopFailure"] = filtered
        else:
            hooks.pop("StopFailure", None)
        SETTINGS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR)
    print("Claude -> Ollama Continuity removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
