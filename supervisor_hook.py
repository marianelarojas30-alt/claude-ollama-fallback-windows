#!/usr/bin/env python3
"""Claude Code lifecycle hook for same-terminal Claude <-> Ollama supervision."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
from typing import Any

# Provider-unavailability conditions that justify switching away from Anthropic.
SUPPORTED_ERRORS = {
    "rate_limit",
    "billing_error",
    "server_error",
    "max_output_tokens",
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def control_dir() -> pathlib.Path | None:
    raw = os.environ.get("CLAUDE_CONTINUITY_CONTROL_DIR")
    if not raw:
        return None
    path = pathlib.Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_signal(name: str, payload: dict[str, Any]) -> None:
    root = control_dir()
    if root is None:
        return
    tmp = root / f"{name}.tmp"
    final = root / name
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, final)


def remove_signal(name: str) -> None:
    root = control_dir()
    if root is None:
        return
    try:
        (root / name).unlink()
    except (FileNotFoundError, OSError):
        pass


def handle(payload: dict[str, Any]) -> int:
    if os.environ.get("CLAUDE_CONTINUITY_PROBE") == "1":
        return 0
    if os.environ.get("CLAUDE_CONTINUITY_SUPERVISED") != "1":
        return 0

    event = str(payload.get("hook_event_name") or "")
    provider = os.environ.get("CLAUDE_CONTINUITY_PROVIDER", "")
    permission_mode = payload.get("permission_mode")

    write_signal(
        "current-session.json",
        {
            "updated_at": now_iso(),
            "session_id": payload.get("session_id"),
            "cwd": payload.get("cwd") or os.getcwd(),
            "transcript_path": payload.get("transcript_path"),
            "permission_mode": permission_mode,
            "provider": provider,
            "event": event,
        },
    )

    if provider == "ollama":
        if event == "UserPromptSubmit":
            remove_signal("fallback-idle.json")
            return 0
        if event == "Stop":
            idle = {
                "created_at": now_iso(),
                "session_id": payload.get("session_id"),
                "cwd": payload.get("cwd") or os.getcwd(),
            }
            write_signal("fallback-idle.json", idle)
            root = control_dir()
            if root is not None and (root / "primary-ready.json").exists():
                write_signal("return-request.json", idle)
            return 0

    if provider == "anthropic" and event == "StopFailure":
        error = str(payload.get("error") or "unknown")
        if error not in SUPPORTED_ERRORS:
            return 0
        write_signal(
            "fallback-request.json",
            {
                "created_at": now_iso(),
                "session_id": payload.get("session_id"),
                "cwd": payload.get("cwd") or os.getcwd(),
                "permission_mode": permission_mode,
                "error": error,
                "error_details": payload.get("error_details"),
                "transcript_path": payload.get("transcript_path"),
                "last_assistant_message": payload.get("last_assistant_message"),
            },
        )
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    return handle(payload)


if __name__ == "__main__":
    raise SystemExit(main())
