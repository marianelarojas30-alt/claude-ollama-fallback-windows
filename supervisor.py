#!/usr/bin/env python3
"""Same-terminal Claude Code <-> Ollama continuity supervisor."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

import continuity

POLL_SECONDS = max(30, int(os.environ.get("CLAUDE_CONTINUITY_PROBE_SECONDS", "300")))
PROBE_TIMEOUT = max(15, int(os.environ.get("CLAUDE_CONTINUITY_PROBE_TIMEOUT", "60")))


def banner(text: str) -> None:
    line = "=" * 72
    print(f"\n{line}\nCLAUDE CONTINUITY: {text}\n{line}\n", flush=True)


def read_json(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def remove(path: pathlib.Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def clean_control(control: pathlib.Path) -> None:
    for name in (
        "fallback-request.json",
        "fallback-idle.json",
        "primary-ready.json",
        "return-request.json",
    ):
        remove(control / name)


def child_env(control: pathlib.Path, provider: str) -> dict[str, str]:
    env = os.environ.copy()
    env["CLAUDE_CONTINUITY_SUPERVISED"] = "1"
    env["CLAUDE_CONTINUITY_PROVIDER"] = provider
    env["CLAUDE_CONTINUITY_CONTROL_DIR"] = str(control)
    if provider == "ollama":
        env["CLAUDE_OLLAMA_FALLBACK_ACTIVE"] = "1"
        env["ANTHROPIC_AUTH_TOKEN"] = "ollama"
        env["ANTHROPIC_API_KEY"] = ""
        env["ANTHROPIC_BASE_URL"] = os.environ.get(
            "CLAUDE_OLLAMA_BASE_URL", "http://localhost:11434"
        )
    else:
        env.pop("CLAUDE_OLLAMA_FALLBACK_ACTIVE", None)
        if env.get("ANTHROPIC_AUTH_TOKEN") == "ollama":
            env.pop("ANTHROPIC_AUTH_TOKEN", None)
        if env.get("ANTHROPIC_API_KEY") == "":
            env.pop("ANTHROPIC_API_KEY", None)
        if env.get("ANTHROPIC_BASE_URL", "").rstrip("/") in {
            "http://localhost:11434",
            "http://127.0.0.1:11434",
        }:
            env.pop("ANTHROPIC_BASE_URL", None)
    return env


def spawn_visible(cmd: list[str], cwd: str, env: dict[str, str]) -> subprocess.Popen[Any]:
    kwargs: dict[str, Any] = {"cwd": cwd, "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(continuity.normalize_exec(cmd), **kwargs)


def stop_child(proc: subprocess.Popen[Any], grace: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        elif os.name != "nt":
            os.killpg(proc.pid, signal.SIGINT)
        else:
            proc.terminate()
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=3)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def probe_primary(control: pathlib.Path, stop_event: threading.Event) -> None:
    claude = shutil.which("claude")
    if not claude:
        return
    probe_root = continuity.state_dir() / "probe"
    probe_root.mkdir(parents=True, exist_ok=True)

    while not stop_event.wait(POLL_SECONDS):
        env = child_env(control, "anthropic")
        env["CLAUDE_CONTINUITY_PROBE"] = "1"
        cmd = [
            claude,
            "-p",
            "Reply exactly READY and do not use tools.",
            "--max-turns",
            "1",
            "--output-format",
            "json",
        ]
        try:
            proc = subprocess.run(
                continuity.normalize_exec(cmd),
                cwd=str(probe_root),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=PROBE_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            payload = {
                "created_at": continuity.now_iso(),
                "probe": "Claude Code request succeeded",
            }
            tmp = control / "primary-ready.json.tmp"
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, control / "primary-ready.json")
            return


def run_primary(cwd: str, control: pathlib.Path, session_id: str | None) -> tuple[str, dict[str, Any] | None, str | None]:
    claude = shutil.which("claude")
    if not claude:
        raise SystemExit("Claude Code executable not found in PATH.")
    remove(control / "fallback-request.json")
    cmd = [claude]
    if session_id:
        cmd.extend(["--resume", session_id])
    banner("CLAUDE ACTIVE")
    proc = spawn_visible(cmd, cwd, child_env(control, "anthropic"))
    request_path = control / "fallback-request.json"
    while proc.poll() is None:
        if request_path.exists():
            request = read_json(request_path) or {}
            new_session = str(request.get("session_id") or session_id or "") or None
            banner(f"CLAUDE LIMIT DETECTED ({request.get('error', 'unknown')}). SWITCHING TO OLLAMA")
            time.sleep(0.5)
            stop_child(proc)
            return "fallback", request, new_session
        time.sleep(0.25)
    return "exit", None, session_id


def fallback_prompt(request: dict[str, Any] | None) -> str:
    request = request or {}
    details = request.get("error_details") or "Claude usage/provider limit"
    return (
        "Continue the exact unfinished coding task from this session. "
        "Claude became unavailable, so you are the local Ollama fallback. "
        "Inspect the current repository and existing conversation before acting. "
        "Do not restart completed work. Preserve unrelated user changes. "
        f"Previous provider failure: {details}."
    )


def run_ollama(cwd: str, control: pathlib.Path, session_id: str | None, request: dict[str, Any] | None) -> tuple[str, str | None]:
    claude = shutil.which("claude")
    if not claude:
        raise SystemExit("Claude Code executable not found in PATH.")
    model = os.environ.get("CLAUDE_OLLAMA_MODEL", continuity.DEFAULT_MODEL)
    permission_mode = os.environ.get("CLAUDE_OLLAMA_PERMISSION_MODE", "acceptEdits")

    remove(control / "return-request.json")
    remove(control / "fallback-idle.json")
    remove(control / "primary-ready.json")

    cmd = [claude, "--model", model]
    if permission_mode == "bypassPermissions":
        cmd.append("--dangerously-skip-permissions")
    else:
        cmd.extend(["--permission-mode", permission_mode])
    if session_id:
        cmd.extend(["--resume", session_id, fallback_prompt(request)])
    else:
        cmd.append(fallback_prompt(request))

    banner(f"OLLAMA ACTIVE ({model}). CLAUDE AVAILABILITY WILL BE CHECKED EVERY {POLL_SECONDS}s")
    proc = spawn_visible(cmd, cwd, child_env(control, "ollama"))
    stop_probe = threading.Event()
    probe = threading.Thread(target=probe_primary, args=(control, stop_probe), daemon=True)
    probe.start()

    idle_path = control / "fallback-idle.json"
    ready_path = control / "primary-ready.json"
    return_path = control / "return-request.json"
    try:
        while proc.poll() is None:
            if return_path.exists():
                banner("CLAUDE IS AVAILABLE AGAIN. RETURNING AT SAFE CHECKPOINT")
                stop_child(proc)
                return "primary", session_id
            if ready_path.exists() and idle_path.exists():
                banner("CLAUDE IS AVAILABLE AGAIN. OLLAMA IS IDLE, RETURNING TO CLAUDE")
                stop_child(proc)
                return "primary", session_id
            time.sleep(0.25)
    finally:
        stop_probe.set()
    if ready_path.exists():
        return "primary", session_id
    return "exit", session_id


def supervise(cwd: str) -> int:
    cwd_path = pathlib.Path(cwd).resolve()
    if not cwd_path.exists() or not cwd_path.is_dir():
        raise SystemExit(f"Working directory does not exist: {cwd_path}")
    control = continuity.state_dir() / "supervisor" / f"{os.getpid()}"
    control.mkdir(parents=True, exist_ok=True)
    clean_control(control)

    ok, detail = continuity.claude_available()
    if not ok:
        raise SystemExit(detail)
    ok, detail = continuity.ollama_available()
    if not ok:
        raise SystemExit(detail)
    model = os.environ.get("CLAUDE_OLLAMA_MODEL", continuity.DEFAULT_MODEL)
    ok, detail = continuity.model_available(model)
    if not ok:
        raise SystemExit(detail)

    session_id: str | None = None
    request: dict[str, Any] | None = None
    provider = "primary"
    try:
        while True:
            if provider == "primary":
                action, request, session_id = run_primary(str(cwd_path), control, session_id)
                if action == "fallback":
                    provider = "ollama"
                    continue
                return 0
            action, session_id = run_ollama(str(cwd_path), control, session_id, request)
            if action == "primary":
                provider = "primary"
                request = None
                remove(control / "primary-ready.json")
                remove(control / "return-request.json")
                remove(control / "fallback-idle.json")
                continue
            return 0
    except KeyboardInterrupt:
        print("\nContinuity supervisor stopped by user.")
        return 130
    finally:
        clean_control(control)
        try:
            control.rmdir()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Same-terminal Claude/Ollama continuity supervisor")
    parser.add_argument("--cwd", default=os.getcwd())
    args = parser.parse_args(argv)
    return supervise(args.cwd)


if __name__ == "__main__":
    raise SystemExit(main())
