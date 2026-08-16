#!/usr/bin/env python3
"""Self-updater for Claude Ollama Continuity."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

REPOSITORY = os.environ.get(
    "CLAUDE_CONTINUITY_REPOSITORY",
    "marianelarojas30-alt/claude-ollama-fallback-windows",
)
BRANCH = os.environ.get("CLAUDE_CONTINUITY_BRANCH", "main")
FILES = [
    "continuity.py",
    "supervisor.py",
    "supervisor_hook.py",
    "install.py",
    "updater.py",
]


def main() -> int:
    base = f"https://raw.githubusercontent.com/{REPOSITORY}/{BRANCH}"
    print(f"Updating Claude Ollama Continuity from {REPOSITORY}@{BRANCH} ...")
    try:
        with tempfile.TemporaryDirectory(prefix="claude-continuity-update-") as tempdir:
            root = pathlib.Path(tempdir)
            for name in FILES:
                url = f"{base}/{name}"
                try:
                    with urllib.request.urlopen(url, timeout=30) as response:
                        data = response.read()
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    print(f"FAILED downloading {name}: {exc}")
                    return 1
                (root / name).write_bytes(data)
                print(f"  downloaded {name}")

            proc = subprocess.run(
                [sys.executable, str(root / "install.py")],
                cwd=str(root),
                check=False,
            )
            if proc.returncode != 0:
                print(f"Update installer failed with exit code {proc.returncode}.")
                return proc.returncode
    except Exception as exc:
        print(f"Update failed: {exc}")
        return 1

    print("\nUPDATE COMPLETE")
    print("Open a NEW terminal before starting the next Claude session.")
    print("Future updates: claude-continuity update")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
