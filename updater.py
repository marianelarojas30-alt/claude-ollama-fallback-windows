#!/usr/bin/env python3
"""Self-updater for Claude Ollama Continuity."""
from __future__ import annotations

import os
import pathlib
import shutil
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
REQUIRED_FILES = [
    "continuity.py",
    "supervisor.py",
    "supervisor_hook.py",
    "install.py",
]
OPTIONAL_FILES = ["updater.py"]


def download(url: str, destination: pathlib.Path) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            destination.write_bytes(response.read())
        return True, ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def main() -> int:
    base = f"https://raw.githubusercontent.com/{REPOSITORY}/{BRANCH}"
    print(f"Updating Claude Ollama Continuity from {REPOSITORY}@{BRANCH} ...")

    with tempfile.TemporaryDirectory(prefix="claude-continuity-update-") as tempdir:
        root = pathlib.Path(tempdir)

        for name in REQUIRED_FILES:
            ok, error = download(f"{base}/{name}", root / name)
            if not ok:
                print(f"FAILED downloading required file {name}: {error}")
                return 1
            print(f"  downloaded {name}")

        for name in OPTIONAL_FILES:
            ok, error = download(f"{base}/{name}", root / name)
            if ok:
                print(f"  downloaded {name}")
                continue

            # The updater is already running locally. If GitHub raw is briefly
            # inconsistent or unavailable for this one file, reuse this copy so
            # the main upgrade can still complete.
            current = pathlib.Path(__file__).resolve()
            if current.exists():
                shutil.copy2(current, root / name)
                print(f"  warning: could not download {name} ({error}); using current updater copy")
            else:
                print(f"FAILED downloading {name}: {error}")
                return 1

        proc = subprocess.run(
            [sys.executable, str(root / "install.py")],
            cwd=str(root),
            check=False,
        )
        if proc.returncode != 0:
            print(f"Update installer failed with exit code {proc.returncode}.")
            return proc.returncode

    print("\nUPDATE COMPLETE")
    print("Open a NEW terminal before starting the next Claude session.")
    print("Future updates: claude-continuity update")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
