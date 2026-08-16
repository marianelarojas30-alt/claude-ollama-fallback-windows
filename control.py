#!/usr/bin/env python3
"""Control helpers for testing the same-terminal continuity supervisor."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import time
from typing import Any

APP = "claude-ollama-continuity"
HEARTBEAT_MAX_AGE = 5.0


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def state_dir() -> pathlib.Path:
    local = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home() / "AppData" / "Local"))
    root = local / APP / "state"
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_json(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def active_control() -> pathlib.Path:
    root = state_dir() / "supervisor"
    if not root.exists():
        raise SystemExit("No active supervised Claude session found. Start `claude` in another terminal first.")

    candidates: list[tuple[float, pathlib.Path]] = []
    now = time.time()
    for path in root.iterdir():
        if not path.is_dir():
            continue
        heartbeat = read_json(path / "heartbeat.json") or {}
        try:
            epoch = float(heartbeat.get("epoch", 0))
        except (TypeError, ValueError):
            epoch = 0
        if epoch and now - epoch <= HEARTBEAT_MAX_AGE:
            candidates.append((epoch, path))

    if not candidates:
        raise SystemExit("No live supervised Claude session found. Start `claude` in another terminal first.")
    candidates.sort(reverse=True, key=lambda item: item[0])
    return candidates[0][1]


def write_signal(root: pathlib.Path, name: str, payload: dict[str, Any]) -> None:
    tmp = root / f"{name}.tmp"
    final = root / name
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, final)


def simulate_limit() -> int:
    root = active_control()
    current = read_json(root / "current-session.json") or {}
    payload = {
        "created_at": now_iso(),
        "session_id": current.get("session_id"),
        "cwd": current.get("cwd") or os.getcwd(),
        "error": "rate_limit",
        "error_details": "SIMULATION ONLY: forced rate_limit for continuity test",
        "transcript_path": current.get("transcript_path"),
        "last_assistant_message": None,
        "simulated": True,
    }
    write_signal(root, "fallback-request.json", payload)
    print("SIMULATED LIMIT SENT")
    print("Watch the terminal where `claude` is running. It should switch to OLLAMA ACTIVE.")
    return 0


def simulate_recovery() -> int:
    root = active_control()
    payload = {
        "created_at": now_iso(),
        "probe": "SIMULATION ONLY: forced Claude recovery",
        "simulated": True,
    }
    write_signal(root, "primary-ready.json", payload)
    write_signal(root, "return-request.json", payload)
    print("SIMULATED RECOVERY SENT")
    print("Watch the terminal where `claude` is running. It should return to CLAUDE ACTIVE.")
    return 0


def status() -> int:
    root = active_control()
    print(f"Active supervisor: {root}")
    for name in (
        "heartbeat.json",
        "current-session.json",
        "fallback-request.json",
        "fallback-idle.json",
        "primary-ready.json",
        "return-request.json",
    ):
        path = root / name
        print(f"{name}: {'present' if path.exists() else 'absent'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claude-continuity")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("simulate-limit")
    sub.add_parser("simulate-recovery")
    sub.add_parser("supervisor-status")
    args = parser.parse_args(argv)
    if args.cmd == "simulate-limit":
        return simulate_limit()
    if args.cmd == "simulate-recovery":
        return simulate_recovery()
    if args.cmd == "supervisor-status":
        return status()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
