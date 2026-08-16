#!/usr/bin/env python3
"""Small, side-effect-free handoff utilities for Claude/Ollama continuity."""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
from typing import Any, Iterable

MAX_TRANSCRIPT_CHARS = 30000


def load_json_lines(path: pathlib.Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    yield value
    except OSError:
        return


def flatten_text(value: Any) -> list[str]:
    output: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        if text:
            output.append(text)
    elif isinstance(value, list):
        for item in value:
            output.extend(flatten_text(item))
    elif isinstance(value, dict):
        for key in ("text", "content", "message", "result", "summary"):
            if key in value:
                output.extend(flatten_text(value[key]))
    return output


def extract_transcript(path_str: str | None, limit: int = MAX_TRANSCRIPT_CHARS) -> str:
    if not path_str:
        return "(No transcript path supplied.)"
    path = pathlib.Path(path_str).expanduser()
    if not path.exists():
        return f"(Transcript not found at {path}.)"

    chunks: list[str] = []
    for event in load_json_lines(path):
        message = event.get("message")
        if isinstance(message, dict):
            role = message.get("role")
            texts = flatten_text(message.get("content"))
        else:
            role = event.get("role") or event.get("type")
            texts = flatten_text(event.get("content"))
        if texts:
            chunks.append(f"[{str(role or 'event').upper()}] " + "\n".join(texts))

    if chunks:
        return "\n\n".join(chunks)[-limit:]
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError as exc:
        return f"(Could not read transcript: {exc})"


def _capture(command: list[str], cwd: str) -> str:
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15,
            check=False,
        )
        return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return f"(command failed: {exc})"


def git_snapshot(cwd: str) -> str:
    git = shutil.which("git")
    if not git:
        return "git not installed"
    if _capture([git, "rev-parse", "--is-inside-work-tree"], cwd).strip() != "true":
        return "Not a git work tree."
    return "\n\n".join(
        [
            "## git status --short\n" + _capture([git, "status", "--short"], cwd),
            "## git diff --stat\n" + _capture([git, "diff", "--stat"], cwd),
            "## recent commits\n" + _capture([git, "log", "-5", "--oneline", "--decorate"], cwd),
        ]
    )
