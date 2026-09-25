#!/usr/bin/env python3
"""Atomic self-updater for Claude Ollama Continuity."""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import urllib.parse

TRUSTED_REPOSITORY = "marianelarojas30-alt/claude-ollama-fallback-windows"
DEFAULT_BRANCH = "main"
REPOSITORY = os.environ.get("CLAUDE_CONTINUITY_REPOSITORY", TRUSTED_REPOSITORY)
BRANCH = os.environ.get("CLAUDE_CONTINUITY_BRANCH", DEFAULT_BRANCH)
ALLOW_CUSTOM_SOURCE = os.environ.get("CLAUDE_CONTINUITY_ALLOW_CUSTOM_SOURCE") == "1"
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


def validate_source() -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", REPOSITORY):
        raise RuntimeError("invalid GitHub repository name")
    if (REPOSITORY != TRUSTED_REPOSITORY or BRANCH != DEFAULT_BRANCH) and not ALLOW_CUSTOM_SOURCE:
        raise RuntimeError(
            "custom update source blocked; set CLAUDE_CONTINUITY_ALLOW_CUSTOM_SOURCE=1 only after reviewing the source"
        )


def resolve_commit() -> str:
    validate_source()
    branch = urllib.parse.quote(BRANCH, safe="")
    url = f"https://api.github.com/repos/{REPOSITORY}/commits/{branch}"
    try:
        payload = json.loads(request_bytes(url).decode("utf-8"))
        sha = str(payload.get("sha") or "")
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not resolve {REPOSITORY}@{BRANCH}: {exc}") from exc
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise RuntimeError("GitHub did not return a valid 40-character commit SHA")
    return sha.lower()


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
