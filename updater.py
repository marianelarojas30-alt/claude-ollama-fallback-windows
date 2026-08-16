#!/usr/bin/env python3
"""Atomic self-updater for Claude Ollama Continuity."""
from __future__ import annotations

import json
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
    "runtime.py",
    "supervisor.py",
    "supervisor_hook.py",
    "control.py",
    "install.py",
    "updater.py",
]


def request_bytes(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "claude-ollama-continuity-updater",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def resolve_commit() -> str:
    url = f"https://api.github.com/repos/{REPOSITORY}/commits/{BRANCH}"
    try:
        payload = json.loads(request_bytes(url).decode("utf-8"))
        sha = str(payload.get("sha") or "")
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not resolve {REPOSITORY}@{BRANCH}: {exc}") from exc
    if len(sha) < 40:
        raise RuntimeError("GitHub did not return a valid commit SHA")
    return sha


def download_commit(commit: str, root: pathlib.Path) -> None:
    base = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}"
    for name in FILES:
        try:
            data = request_bytes(f"{base}/{name}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"failed downloading {name} from {commit[:12]}: {exc}") from exc
        if not data:
            raise RuntimeError(f"downloaded empty required file: {name}")
        (root / name).write_bytes(data)
        print(f"  downloaded {name}")


def main() -> int:
    print(f"Updating Claude Ollama Continuity from {REPOSITORY}@{BRANCH} ...")
    try:
        commit = resolve_commit()
    except RuntimeError as exc:
        print(f"UPDATE FAILED: {exc}")
        return 1

    print(f"Pinned commit: {commit}")
    with tempfile.TemporaryDirectory(prefix="claude-continuity-update-") as tempdir:
        root = pathlib.Path(tempdir)
        try:
            download_commit(commit, root)
        except RuntimeError as exc:
            print(f"UPDATE FAILED: {exc}")
            return 1

        env = os.environ.copy()
        env["CLAUDE_CONTINUITY_COMMIT"] = commit
        proc = subprocess.run(
            [sys.executable, str(root / "install.py")],
            cwd=str(root),
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            print(f"UPDATE FAILED: installer exited with {proc.returncode}")
            return proc.returncode

    print("\nUPDATE COMPLETE")
    print(f"Installed commit: {commit}")
    print("Open a NEW terminal before starting the next Claude session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
