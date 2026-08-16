#!/usr/bin/env python3
"""Diagnostics and explicit test controls for Claude/Ollama continuity."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import time
from typing import Any

import runtime

HEARTBEAT_MAX_AGE = 5.0


def state_dir() -> pathlib.Path:
    return runtime.state_dir()


def read_json(path: pathlib.Path) -> dict[str, Any] | None:
    return runtime.read_json(path)


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
    supervisor = read_json(path / "supervisor.json") or {}
    current = read_json(path / "current-session.json") or {}
    pid = heartbeat.get("pid") or supervisor.get("pid") or path.name
    provider = current.get("provider") or "starting"
    cwd = current.get("cwd") or heartbeat.get("cwd") or supervisor.get("cwd") or "(unknown cwd)"
    session_id = current.get("session_id") or "(session id pending)"
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
        + "\nUse --pid <PID> to target the exact session."
    )


def write_signal(root: pathlib.Path, name: str, payload: dict[str, Any]) -> None:
    tmp = root / f"{name}.tmp"
    final = root / name
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, final)


def simulate_limit(pid: int | None = None) -> int:
    root = active_control(pid)
    current = read_json(root / "current-session.json") or {}
    supervisor = read_json(root / "supervisor.json") or {}
    payload = {
        "created_at": runtime.now_iso(),
        "session_id": current.get("session_id"),
        "cwd": current.get("cwd") or supervisor.get("cwd") or os.getcwd(),
        "permission_mode": current.get("permission_mode"),
        "error": "rate_limit",
        "error_details": "SIMULATION ONLY: forced rate_limit for continuity test",
        "transcript_path": current.get("transcript_path"),
        "last_assistant_message": None,
        "simulated": True,
    }
    write_signal(root, "fallback-request.json", payload)
    print(f"SIMULATED LIMIT SENT TO SUPERVISOR PID {root.name}")
    print("Watch that terminal. It should switch from CLAUDE ACTIVE to OLLAMA ACTIVE.")
    return 0


def simulate_recovery(pid: int | None = None) -> int:
    root = active_control(pid)
    write_signal(
        root,
        "primary-ready.json",
        {
            "created_at": runtime.now_iso(),
            "probe": "SIMULATION ONLY: forced Claude recovery",
            "simulated": True,
        },
    )
    print(f"SIMULATED RECOVERY SENT TO SUPERVISOR PID {root.name}")
    print("Claude is marked available. Return waits for Ollama's next safe Stop/idle checkpoint.")
    return 0


def status(pid: int | None = None) -> int:
    root = active_control(pid)
    print("Active supervisor: " + describe(root))
    for name in (
        "heartbeat.json",
        "supervisor.json",
        "current-session.json",
        "fallback-request.json",
        "fallback-idle.json",
        "primary-ready.json",
        "return-request.json",
    ):
        print(f"{name}: {'present' if (root / name).exists() else 'absent'}")
    return 0


def _hook_configured() -> tuple[bool, str]:
    settings = pathlib.Path.home() / ".claude" / "settings.json"
    if not settings.exists():
        return False, f"settings not found: {settings}"
    try:
        data = json.loads(settings.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"settings unreadable: {exc}"
    hooks = data.get("hooks", {})
    marker = str(runtime.install_dir() / "supervisor_hook.py")
    required = ("StopFailure", "Stop", "UserPromptSubmit")
    missing = [event for event in required if marker not in json.dumps(hooks.get(event, []))]
    if missing:
        return False, "missing hook events: " + ", ".join(missing)
    return True, "StopFailure, Stop and UserPromptSubmit configured"


def _wrapper_first() -> tuple[bool, str]:
    wrapper = runtime.install_dir() / "bin" / ("claude.cmd" if os.name == "nt" else "claude")
    resolved = shutil.which("claude")
    if not resolved:
        return False, "claude is not resolvable from PATH"
    try:
        same = pathlib.Path(resolved).resolve() == wrapper.resolve()
    except OSError:
        same = os.path.normcase(resolved) == os.path.normcase(str(wrapper))
    return same, f"resolved={resolved}; expected={wrapper}"


def doctor() -> int:
    config = runtime.config()
    model = os.environ.get("CLAUDE_OLLAMA_MODEL", runtime.DEFAULT_MODEL)
    checks: list[tuple[str, bool, str]] = []

    runtime_files = ("continuity.py", "runtime.py", "supervisor.py", "supervisor_hook.py", "control.py", "updater.py")
    missing = [name for name in runtime_files if not (runtime.install_dir() / name).exists()]
    checks.append(("Installed runtime", not missing, "complete" if not missing else "missing: " + ", ".join(missing)))

    ok, detail = _wrapper_first()
    checks.append(("Global claude wrapper", ok, detail))

    ok, detail = runtime.claude_available()
    checks.append(("Real Claude Code", ok, detail))

    ok, detail = runtime.ollama_available()
    checks.append(("Ollama", ok, detail.splitlines()[0] if detail else "available"))

    ok, detail = runtime.model_available(model)
    checks.append((f"Ollama model {model}", ok, detail))

    ok, detail = _hook_configured()
    checks.append(("Claude hooks", ok, detail))

    print(f"Claude Ollama Continuity {runtime.VERSION}")
    print(f"Installed commit: {config.get('installed_commit') or '(unknown / pre-1.0 install)'}")
    print(f"Install dir: {runtime.install_dir()}\n")
    for name, passed, detail in checks:
        print(f"{'OK' if passed else 'FAIL':4}  {name}: {detail}")

    if all(item[1] for item in checks):
        print("\nREADY: automatic Claude -> Ollama -> Claude continuity is configured.")
        return 0
    print("\nNOT READY: fix the FAIL items before relying on automatic takeover.")
    return 1


def version() -> int:
    config = runtime.config()
    print(f"Claude Ollama Continuity {runtime.VERSION}")
    print(f"Installed commit: {config.get('installed_commit') or '(unknown)'}")
    return 0


def add_pid_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pid", type=int, default=None, help="Exact supervisor PID to target")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claude-continuity")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("version")
    sub.add_parser("sessions")
    limit_parser = sub.add_parser("simulate-limit")
    add_pid_argument(limit_parser)
    recovery_parser = sub.add_parser("simulate-recovery")
    add_pid_argument(recovery_parser)
    status_parser = sub.add_parser("supervisor-status")
    add_pid_argument(status_parser)
    args = parser.parse_args(argv)

    if args.cmd == "doctor":
        return doctor()
    if args.cmd == "version":
        return version()
    if args.cmd == "sessions":
        return sessions()
    if args.cmd == "simulate-limit":
        return simulate_limit(args.pid)
    if args.cmd == "simulate-recovery":
        return simulate_recovery(args.pid)
    if args.cmd == "supervisor-status":
        return status(args.pid)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
