#!/usr/bin/env python3
"""Same-terminal Claude Code <-> Ollama continuity supervisor."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import signal
import subprocess
import threading
import time
from typing import Any

import continuity
import runtime

RETRY_SECONDS = max(30, int(os.environ.get("CLAUDE_CONTINUITY_RETRY_SECONDS", "300")))
HANDOFF_CHARS = max(4000, int(os.environ.get("CLAUDE_CONTINUITY_HANDOFF_CHARS", "30000")))
HANDBACK_CHARS = max(4000, int(os.environ.get("CLAUDE_CONTINUITY_HANDBACK_CHARS", "30000")))
PASSTHROUGH_FLAGS = {"--help", "-h", "--version", "-v"}
PASSTHROUGH_COMMANDS = {"update", "install", "doctor", "mcp", "config"}


def banner(text: str) -> None:
    line = "=" * 72
    print(f"\n{line}\nCLAUDE CONTINUITY: {text}\n{line}\n", flush=True)


def read_json(path: pathlib.Path) -> dict[str, Any] | None:
    return runtime.read_json(path)


def remove(path: pathlib.Path) -> None:
    try:
        path.unlink()
    except (FileNotFoundError, OSError):
        pass


def clean_control(control: pathlib.Path) -> None:
    for name in (
        "fallback-request.json",
        "fallback-idle.json",
        "force-return.json",
        "current-session.json",
        "heartbeat.json",
        "supervisor.json",
    ):
        remove(control / name)


def real_claude() -> str:
    candidate = runtime.real_claude_executable()
    if candidate:
        return candidate
    raise SystemExit("Real Claude Code executable not found. Run claude-continuity update.")


def child_env(control: pathlib.Path, provider: str) -> dict[str, str]:
    return runtime.fallback_environment(control) if provider == "ollama" else runtime.primary_environment(control)


def spawn_visible(cmd: list[str], cwd: str, env: dict[str, str]) -> subprocess.Popen[Any]:
    kwargs: dict[str, Any] = {"cwd": cwd, "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(runtime.normalize_exec(cmd), **kwargs)


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


def write_json_atomic(path: pathlib.Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def heartbeat_loop(control: pathlib.Path, cwd: str, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            write_json_atomic(
                control / "heartbeat.json",
                {"pid": os.getpid(), "cwd": cwd, "updated_at": runtime.now_iso(), "epoch": time.time()},
            )
        except OSError:
            pass
        stop_event.wait(1.0)


def fallback_readiness(model: str) -> tuple[bool, str]:
    ok, detail = runtime.ollama_available()
    if not ok:
        return False, detail
    ok, detail = runtime.model_available(model)
    if not ok:
        return False, detail + f". Run: ollama pull {model}"
    return True, detail


def build_primary_command(
    primary_session_id: str | None,
    initial_args: list[str],
    handback_prompt: str | None = None,
) -> list[str]:
    cmd = [real_claude()]
    if primary_session_id:
        cmd.extend(["--resume", primary_session_id])
        if handback_prompt:
            cmd.append(handback_prompt)
    else:
        cmd.extend(initial_args)
    return cmd


def fallback_from_signal(
    request_path: pathlib.Path,
    primary_session_id: str | None,
) -> tuple[dict[str, Any], str | None] | None:
    if not request_path.exists():
        return None
    request = read_json(request_path) or {}
    captured = str(request.get("session_id") or primary_session_id or "") or None
    return request, captured


def run_primary(
    cwd: str,
    control: pathlib.Path,
    primary_session_id: str | None,
    initial_args: list[str],
    handback_prompt: str | None = None,
) -> tuple[str, dict[str, Any] | None, str | None, int]:
    remove(control / "fallback-request.json")
    banner("CLAUDE ACTIVE")
    proc = spawn_visible(
        build_primary_command(primary_session_id, initial_args, handback_prompt),
        cwd,
        child_env(control, "anthropic"),
    )
    request_path = control / "fallback-request.json"

    while proc.poll() is None:
        signaled = fallback_from_signal(request_path, primary_session_id)
        if signaled is not None:
            request, captured = signaled
            banner(f"CLAUDE LIMIT DETECTED ({request.get('error', 'unknown')})")
            stop_child(proc)
            return "fallback", request, captured, 0
        time.sleep(0.15)

    # StopFailure may be written at the same moment the CLI exits.
    signaled = fallback_from_signal(request_path, primary_session_id)
    if signaled is not None:
        request, captured = signaled
        banner(f"CLAUDE LIMIT DETECTED ({request.get('error', 'unknown')})")
        return "fallback", request, captured, 0

    return "exit", None, primary_session_id, int(proc.returncode or 0)


def fallback_prompt(cwd: str, request: dict[str, Any] | None) -> str:
    request = request or {}
    transcript = continuity.extract_transcript(request.get("transcript_path"), limit=HANDOFF_CHARS)
    snapshot = continuity.git_snapshot(cwd)
    details = request.get("error_details") or request.get("last_assistant_message") or "Claude provider limit"
    return f"""You are the temporary Ollama fallback for an interrupted Claude Code session.

The Anthropic session stopped because of: {request.get('error', 'unknown')}.
Details: {details}

Continue the exact unfinished task in the current repository. The files on disk are the source of truth. Inspect the repository before changing anything. Do not restart completed work. Preserve unrelated user changes. Run relevant checks for work you change. Continue independently until the current task is complete or genuinely requires user input.

Do not commit, push, publish, deploy, delete remote data, expose secrets, or make account-level changes unless the original user request explicitly required that action.

IMPORTANT SESSION RULE
You are running in a separate Ollama-backed Claude Code session. Never resume or modify the original Anthropic session. Your work will be handed back through repository state and transcript excerpts.

CURRENT REPOSITORY SNAPSHOT
{snapshot}

RECENT ANTHROPIC TRANSCRIPT
{transcript}
"""


def resolved_permission_mode(request: dict[str, Any] | None) -> str:
    explicit = os.environ.get("CLAUDE_OLLAMA_PERMISSION_MODE")
    if explicit:
        return explicit
    return str((request or {}).get("permission_mode") or "default")


def build_ollama_command(model: str, permission_mode: str, prompt: str) -> list[str]:
    cmd = [real_claude(), "--model", model]
    if permission_mode == "bypassPermissions":
        cmd.append("--dangerously-skip-permissions")
    elif permission_mode:
        cmd.extend(["--permission-mode", permission_mode])
    cmd.append(prompt)
    return cmd


def build_handback_prompt(cwd: str, control: pathlib.Path) -> str:
    current = read_json(control / "current-session.json") or {}
    transcript_path = current.get("transcript_path") if current.get("provider") == "ollama" else None
    transcript = continuity.extract_transcript(transcript_path, limit=HANDBACK_CHARS)
    snapshot = continuity.git_snapshot(cwd)
    return f"""The Anthropic session is resuming after a temporary Ollama fallback.

Ollama ran in a separate Claude Code session so your original Anthropic session and model metadata remained intact. Continue the user's unfinished task from the repository's current state. Review changes on disk before doing more work. Do not redo completed work. Preserve unrelated user changes.

CURRENT REPOSITORY SNAPSHOT AFTER OLLAMA
{snapshot}

RECENT OLLAMA FALLBACK TRANSCRIPT
{transcript}
"""


def ollama_is_safely_idle(control: pathlib.Path) -> bool:
    if not (control / "fallback-idle.json").exists():
        return False
    current = read_json(control / "current-session.json") or {}
    return current.get("provider") == "ollama" and current.get("event") == "Stop"


def run_ollama(
    cwd: str,
    control: pathlib.Path,
    request: dict[str, Any] | None,
) -> tuple[str, str | None, int]:
    model = os.environ.get("CLAUDE_OLLAMA_MODEL", runtime.DEFAULT_MODEL)
    ok, detail = fallback_readiness(model)
    if not ok:
        banner("FALLBACK NOT READY")
        print(detail, flush=True)
        print("Run `claude-continuity doctor` and `claude-continuity self-test`.", flush=True)
        return "exit", None, 78

    permission_mode = resolved_permission_mode(request)
    for name in ("fallback-idle.json", "force-return.json", "current-session.json"):
        remove(control / name)

    retry_at = time.time() + RETRY_SECONDS
    banner(f"OLLAMA ACTIVE ({model}). CLAUDE RETRY IN {RETRY_SECONDS}s")
    proc = spawn_visible(
        build_ollama_command(model, permission_mode, fallback_prompt(cwd, request)),
        cwd,
        child_env(control, "ollama"),
    )

    while proc.poll() is None:
        forced = (control / "force-return.json").exists()
        due = time.time() >= retry_at
        if (forced or due) and ollama_is_safely_idle(control):
            handback = build_handback_prompt(cwd, control)
            banner("RETRYING CLAUDE AT SAFE CHECKPOINT")
            stop_child(proc)
            return "primary", handback, 0
        time.sleep(0.15)

    return "exit", None, int(proc.returncode or 0)


def should_passthrough(args: list[str]) -> bool:
    return any(arg in PASSTHROUGH_FLAGS for arg in args) or bool(args and args[0] in PASSTHROUGH_COMMANDS)


def supervise(cwd: str, claude_args: list[str]) -> int:
    cwd_path = pathlib.Path(cwd).resolve()
    if not cwd_path.exists() or not cwd_path.is_dir():
        raise SystemExit(f"Working directory does not exist: {cwd_path}")

    if should_passthrough(claude_args):
        env = os.environ.copy()
        env["CLAUDE_CONTINUITY_INTERNAL"] = "1"
        return subprocess.call(
            runtime.normalize_exec([real_claude(), *claude_args]),
            cwd=str(cwd_path),
            env=env,
        )

    control = runtime.state_dir() / "supervisor" / f"{os.getpid()}"
    control.mkdir(parents=True, exist_ok=True)
    clean_control(control)
    write_json_atomic(
        control / "supervisor.json",
        {"pid": os.getpid(), "cwd": str(cwd_path), "started_at": runtime.now_iso()},
    )

    primary_session_id: str | None = None
    request: dict[str, Any] | None = None
    provider = "primary"
    first_args = list(claude_args)
    pending_handback: str | None = None

    heartbeat_stop = threading.Event()
    threading.Thread(
        target=heartbeat_loop,
        args=(control, str(cwd_path), heartbeat_stop),
        daemon=True,
    ).start()

    try:
        while True:
            if provider == "primary":
                action, request, primary_session_id, code = run_primary(
                    str(cwd_path), control, primary_session_id, first_args, pending_handback
                )
                first_args = []
                pending_handback = None
                if action == "fallback":
                    provider = "ollama"
                    continue
                return code

            action, handback, code = run_ollama(str(cwd_path), control, request)
            if action == "primary":
                provider = "primary"
                request = None
                pending_handback = handback
                for name in ("fallback-idle.json", "force-return.json", "current-session.json"):
                    remove(control / name)
                continue
            return code
    except KeyboardInterrupt:
        print("\nContinuity supervisor stopped by user.")
        return 130
    finally:
        heartbeat_stop.set()
        clean_control(control)
        try:
            control.rmdir()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("claude_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    forwarded = list(args.claude_args)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    return supervise(args.cwd, forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
