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


def live_controls() -> list[pathlib.Path]:
    root = state_dir() / "supervisor"
    if not root.exists():
        return []
    now = time.time()
    live: list[tuple[float, pathlib.Path]] = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        heartbeat = read_json(path / "heartbeat.json") or {}
        try:
            epoch = float(heartbeat.get("epoch", 0))
        except (TypeError, ValueError):
            epoch = 0
        if epoch and 0 <= now - epoch <= HEARTBEAT_MAX_AGE:
            live.append((epoch, path))
    live.sort(reverse=True, key=lambda item: item[0])
    return [path for _, path in live]


def describe(path: pathlib.Path) -> str:
    heartbeat = read_json(path / "heartbeat.json") or {}
    current = read_json(path / "current-session.json") or {}
    pid = heartbeat.get("pid") or path.name
    provider = current.get("provider") or "starting"
    cwd = current.get("cwd") or "(session has not emitted a hook yet)"
    session_id = current.get("session_id") or "(unknown)"
    return f"PID {pid} | {provider} | {cwd} | session {session_id}"


def sessions() -> int:
    live = live_controls()
    if not live:
        print("No live supervised Claude sessions found.")
        return 1
    print("Live supervised Claude sessions:")
    for path in live:
        print("  " + describe(path))
    return 0


def active_control(pid: int | None = None) -> pathlib.Path:
    live = live_controls()
    if not live:
        raise SystemExit("No live supervised Claude session found. Start `claude` first.")

    if pid is not None:
        target = str(pid)
        for path in live:
            heartbeat = read_json(path / "heartbeat.json") or {}
            actual = str(heartbeat.get("pid") or path.name)
            if actual == target:
                return path
        available = "\n".join("  " + describe(path) for path in live)
        raise SystemExit(f"Supervisor PID {pid} is not live. Available sessions:\n{available}")

    if len(live) == 1:
        return live[0]

    available = "\n".join("  " + describe(path) for path in live)
    raise SystemExit(
        "Multiple live supervised Claude sessions found. Refusing to guess.\n"
        + available
        + "\nRun `claude-continuity simulate-limit --pid <PID>` for the exact target."
    )


def write_signal(root: pathlib.Path, name: str, payload: dict[str, Any]) -> None:
    tmp = root / f"{name}.tmp"
    final = root / name
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, final)


def simulate_limit(pid: int | None = None) -> int:
    root = active_control(pid)
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
    print(f"SIMULATED LIMIT SENT TO SUPERVISOR PID {root.name}")
    print("Watch that Claude terminal. It should switch to OLLAMA ACTIVE.")
    return 0


def simulate_recovery(pid: int | None = None) -> int:
    root = active_control(pid)
    payload = {
        "created_at": now_iso(),
        "probe": "SIMULATION ONLY: forced Claude recovery",
        "simulated": True,
    }
    write_signal(root, "primary-ready.json", payload)
    print(f"SIMULATED RECOVERY SENT TO SUPERVISOR PID {root.name}")
    print("Claude is marked available. Ollama will return at its next safe Stop/idle checkpoint.")
    return 0


def status(pid: int | None = None) -> int:
    root = active_control(pid)
    print("Active supervisor: " + describe(root))
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


def add_pid_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pid", type=int, default=None, help="Exact supervisor PID to target")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claude-continuity")
    sub = parser.add_subparsers(dest="cmd", required=True)
    limit_parser = sub.add_parser("simulate-limit")
    add_pid_argument(limit_parser)
    recovery_parser = sub.add_parser("simulate-recovery")
    add_pid_argument(recovery_parser)
    status_parser = sub.add_parser("supervisor-status")
    add_pid_argument(status_parser)
    sub.add_parser("sessions")
    args = parser.parse_args(argv)
    if args.cmd == "simulate-limit":
        return simulate_limit(args.pid)
    if args.cmd == "simulate-recovery":
        return simulate_recovery(args.pid)
    if args.cmd == "supervisor-status":
        return status(args.pid)
    if args.cmd == "sessions":
        return sessions()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
