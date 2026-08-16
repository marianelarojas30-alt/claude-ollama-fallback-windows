#!/usr/bin/env python3
"""Claude Code -> Ollama continuity bridge, Windows-first and cross-platform."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable

APP_NAME = "claude-ollama-continuity"
DEFAULT_MODEL = os.environ.get("CLAUDE_OLLAMA_MODEL", "qwen3.5")
DEFAULT_ERRORS = {
    "rate_limit",
    "billing_error",
    "server_error",
    "max_output_tokens",
}
MAX_TRANSCRIPT_CHARS = int(os.environ.get("CLAUDE_OLLAMA_TRANSCRIPT_CHARS", "50000"))
LOCK_STALE_SECONDS = int(os.environ.get("CLAUDE_OLLAMA_LOCK_STALE_SECONDS", "21600"))


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def state_dir() -> pathlib.Path:
    override = os.environ.get("CLAUDE_OLLAMA_STATE_DIR")
    if override:
        root = pathlib.Path(override).expanduser()
    elif os.name == "nt":
        local = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home() / "AppData" / "Local"))
        root = local / APP_NAME / "state"
    else:
        root = pathlib.Path.home() / ".local" / "state" / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_slug(value: str, fallback: str = "session") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value or "").strip("-.")
    return cleaned[:80] or fallback


def load_json_lines(path: pathlib.Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def flatten_text(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        if text:
            out.append(text)
    elif isinstance(value, list):
        for item in value:
            out.extend(flatten_text(item))
    elif isinstance(value, dict):
        for key in ("text", "content", "message", "result", "summary"):
            if key in value:
                out.extend(flatten_text(value[key]))
    return out


def extract_transcript(path_str: str | None, limit: int = MAX_TRANSCRIPT_CHARS) -> str:
    if not path_str:
        return "(No transcript path supplied by Claude Code.)"
    path = pathlib.Path(path_str).expanduser()
    if not path.exists():
        return f"(Transcript not found at {path}.)"

    chunks: list[str] = []
    for obj in load_json_lines(path):
        msg = obj.get("message")
        if isinstance(msg, dict):
            role = msg.get("role")
            texts = flatten_text(msg.get("content"))
        else:
            role = obj.get("role") or obj.get("type")
            texts = flatten_text(obj.get("content"))
        if texts:
            chunks.append(f"[{str(role or 'event').upper()}] " + "\n".join(texts))

    if chunks:
        return "\n\n".join(chunks)[-limit:]
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError as exc:
        return f"(Could not read transcript: {exc})"


def normalize_exec(cmd: list[str]) -> list[str]:
    if os.name == "nt" and cmd:
        suffix = pathlib.Path(cmd[0]).suffix.lower()
        if suffix in {".cmd", ".bat"}:
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", *cmd]
    return cmd


def run_capture(cmd: list[str], cwd: str | None = None, timeout: int = 15) -> str:
    try:
        proc = subprocess.run(
            normalize_exec(cmd),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return f"(command failed: {exc})"


def git_snapshot(cwd: str) -> str:
    git = shutil.which("git")
    if not git:
        return "git not installed"
    if run_capture([git, "rev-parse", "--is-inside-work-tree"], cwd=cwd).strip() != "true":
        return "Not a git work tree."
    return "\n\n".join(
        [
            "## git status --short\n" + run_capture([git, "status", "--short"], cwd=cwd),
            "## git diff --stat\n" + run_capture([git, "diff", "--stat"], cwd=cwd),
            "## recent commits\n" + run_capture([git, "log", "-5", "--oneline", "--decorate"], cwd=cwd),
        ]
    )


def build_prompt(bundle: dict[str, Any]) -> str:
    return f"""You are the continuity worker taking over an interrupted Claude Code coding session.

The previous provider stopped because of: {bundle.get('error', 'unknown')}.
Error details: {bundle.get('error_details') or '(none)'}
Original working directory: {bundle.get('cwd')}
Handoff time: {bundle.get('created_at')}

GOAL
Continue the unfinished work from the interrupted session. Work directly in the current repository. Do not restart completed work. Inspect current files and git state first, infer the latest unfinished task from the transcript, then continue implementing it. Run relevant tests/checks and fix failures you introduce.

SAFETY AND CONTINUITY
- The repository on disk is the source of truth.
- Preserve existing user changes and unrelated modifications.
- Never reveal secrets, credentials, environment-file contents, tokens, or keychain data.
- Avoid destructive or irreversible actions unless the prior user request clearly required them.
- Inspect code, task files, git diff and transcript before guessing.
- Do not commit, push, publish, deploy, delete remote data, or change account settings unless the original user request explicitly required it.
- At the end write .claude/ollama-continuity-last.md with changes, tests and blockers.

CURRENT REPOSITORY SNAPSHOT
{bundle.get('git_snapshot', '')}

RECENT CLAUDE TRANSCRIPT
{bundle.get('transcript_excerpt', '')}
"""


def acquire_lock(session_id: str) -> pathlib.Path | None:
    lock = state_dir() / f"{safe_slug(session_id)}.lock"
    if lock.exists():
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            age = 0
        if age < LOCK_STALE_SECONDS:
            return None
        try:
            lock.unlink()
        except OSError:
            return None
    try:
        fd = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "created_at": now_iso()}))
        return lock
    except FileExistsError:
        return None


def release_lock(lock: pathlib.Path | None) -> None:
    if not lock:
        return
    try:
        lock.unlink()
    except OSError:
        pass


def allowed_error(error: str) -> bool:
    raw = os.environ.get("CLAUDE_OLLAMA_ERRORS")
    allowed = DEFAULT_ERRORS if not raw else {item.strip() for item in raw.split(",") if item.strip()}
    return error in allowed


def spawn_worker(bundle_path: pathlib.Path, cwd: str, env: dict[str, str]) -> None:
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [sys.executable, str(pathlib.Path(__file__).resolve()), "worker", str(bundle_path)],
        **kwargs,
    )


def handle_hook(payload: dict[str, Any]) -> int:
    if os.environ.get("CLAUDE_OLLAMA_FALLBACK_ACTIVE") == "1":
        return 0
    if payload.get("hook_event_name") != "StopFailure":
        return 0

    error = str(payload.get("error") or "unknown")
    if not allowed_error(error):
        return 0

    cwd = str(payload.get("cwd") or os.getcwd())
    if not pathlib.Path(cwd).exists():
        cwd = os.getcwd()

    session_id = str(payload.get("session_id") or f"unknown-{int(time.time())}")
    lock = acquire_lock(session_id)
    if lock is None:
        return 0

    created = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = state_dir() / "runs" / f"{created}-{safe_slug(session_id)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "created_at": now_iso(),
        "session_id": session_id,
        "cwd": cwd,
        "error": error,
        "error_details": payload.get("error_details"),
        "last_assistant_message": payload.get("last_assistant_message"),
        "transcript_path": payload.get("transcript_path"),
        "transcript_excerpt": extract_transcript(payload.get("transcript_path")),
        "git_snapshot": git_snapshot(cwd),
        "model": os.environ.get("CLAUDE_OLLAMA_MODEL", DEFAULT_MODEL),
        "permission_mode": os.environ.get("CLAUDE_OLLAMA_PERMISSION_MODE", "acceptEdits"),
        "lock_path": str(lock),
    }
    bundle_path = run_dir / "handoff.json"
    bundle_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "handoff.md").write_text(build_prompt(bundle), encoding="utf-8")

    env = os.environ.copy()
    env["CLAUDE_OLLAMA_FALLBACK_ACTIVE"] = "1"
    env["CLAUDE_OLLAMA_RUN_DIR"] = str(run_dir)
    try:
        spawn_worker(bundle_path, cwd, env)
    except OSError:
        release_lock(lock)
        return 1
    return 0


def ollama_available() -> tuple[bool, str]:
    exe = shutil.which("ollama")
    if not exe:
        return False, "ollama executable not found in PATH"
    out = run_capture([exe, "list"], timeout=20)
    if out.startswith("(command failed:"):
        return False, out
    return True, out


def model_available(model: str) -> tuple[bool, str]:
    exe = shutil.which("ollama")
    if not exe:
        return False, "ollama executable not found in PATH"
    out = run_capture([exe, "list"], timeout=20)
    if out.startswith("(command failed:"):
        return False, out
    names: list[str] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if parts:
            names.append(parts[0])
    if model in names or any(name.split(":", 1)[0] == model for name in names):
        return True, f"{model} is installed"
    return False, f"{model} not found; run: ollama pull {model}"


def claude_available() -> tuple[bool, str]:
    exe = shutil.which("claude")
    if not exe:
        return False, "claude executable not found in PATH"
    out = run_capture([exe, "--version"], timeout=20)
    if out.startswith("(command failed:"):
        return False, out
    return True, out or "claude found"


def worker(bundle_path: pathlib.Path) -> int:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    run_dir = bundle_path.parent
    lock = pathlib.Path(bundle["lock_path"]) if bundle.get("lock_path") else None
    log_path = run_dir / "worker.log"
    result_path = run_dir / "result.json"
    cwd = str(bundle.get("cwd") or os.getcwd())
    model = str(bundle.get("model") or DEFAULT_MODEL)
    permission_mode = str(bundle.get("permission_mode") or "acceptEdits")
    prompt = (run_dir / "handoff.md").read_text(encoding="utf-8")
    result: dict[str, Any] = {
        "started_at": now_iso(),
        "model": model,
        "cwd": cwd,
        "status": "starting",
    }

    try:
        ok, detail = ollama_available()
        if not ok:
            result.update(status="failed", reason=detail)
            return 2
        ok, detail = model_available(model)
        if not ok:
            result.update(status="failed", reason=detail)
            return 4
        ok, detail = claude_available()
        if not ok:
            result.update(status="failed", reason=detail)
            return 3

        ollama = shutil.which("ollama") or "ollama"
        cmd = [ollama, "launch", "claude", "--model", model, "--yes", "--"]
        if permission_mode == "bypassPermissions":
            cmd.append("--dangerously-skip-permissions")
        else:
            cmd.extend(["--permission-mode", permission_mode])
        cmd.extend(["-p", prompt])
        result["command"] = shlex.join(cmd[:7] + ["<claude args>"])

        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"[{now_iso()}] starting Ollama continuity worker\n")
            log.write(f"model={model}\ncwd={cwd}\npermission_mode={permission_mode}\n\n")
            log.flush()
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                env=os.environ.copy(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )

        result.update(
            status="completed" if proc.returncode == 0 else "failed",
            returncode=proc.returncode,
            finished_at=now_iso(),
            log=str(log_path),
        )
        return proc.returncode
    except Exception as exc:
        result.update(status="failed", reason=repr(exc), finished_at=now_iso())
        return 10
    finally:
        try:
            result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        except OSError:
            pass
        release_lock(lock)


def latest_run() -> pathlib.Path | None:
    root = state_dir() / "runs"
    if not root.exists():
        return None
    dirs = [path for path in root.iterdir() if path.is_dir()]
    return max(dirs, key=lambda path: path.name) if dirs else None


def cmd_status() -> int:
    run = latest_run()
    if not run:
        print("No continuity runs recorded yet.")
        return 0
    print(f"Latest run: {run}")
    result = run / "result.json"
    print(result.read_text(encoding="utf-8") if result.exists() else "Worker may still be running.")
    return 0


def cmd_logs() -> int:
    run = latest_run()
    if not run:
        print("No continuity runs recorded yet.")
        return 0
    log = run / "worker.log"
    if not log.exists():
        print(f"No worker log yet. Run directory: {run}")
        return 0
    print(log.read_text(encoding="utf-8", errors="replace"))
    return 0


def cmd_doctor() -> int:
    checks: list[tuple[str, bool, str]] = []
    ok, detail = claude_available()
    checks.append(("Claude Code", ok, detail))
    ok, detail = ollama_available()
    checks.append(("Ollama", ok, detail.splitlines()[0] if detail else "available"))

    model = os.environ.get("CLAUDE_OLLAMA_MODEL", DEFAULT_MODEL)
    ok, detail = model_available(model)
    checks.append(("Ollama model", ok, detail))

    settings = pathlib.Path.home() / ".claude" / "settings.json"
    hook_ok = False
    hook_detail = "not installed"
    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8-sig"))
            blob = json.dumps(data.get("hooks", {}).get("StopFailure", []))
            hook_ok = APP_NAME in blob or "continuity.py" in blob
            hook_detail = "configured" if hook_ok else "StopFailure hook not found"
        except Exception as exc:
            hook_detail = f"settings unreadable: {exc}"
    checks.append(("StopFailure hook", hook_ok, hook_detail))

    print("Claude -> Ollama Continuity doctor\n")
    for name, passed, desc in checks:
        print(f"{'OK' if passed else 'FAIL':4}  {name}: {desc}")
    print(f"\nModel: {model}")
    print(f"Permission mode: {os.environ.get('CLAUDE_OLLAMA_PERMISSION_MODE', 'acceptEdits')}")
    print(f"State dir: {state_dir()}")
    return 0 if all(item[1] for item in checks) else 1


def cmd_manual(prompt: str | None) -> int:
    fake: dict[str, Any] = {
        "hook_event_name": "StopFailure",
        "error": "rate_limit",
        "error_details": "manual takeover requested",
        "session_id": f"manual-{int(time.time())}",
        "cwd": os.getcwd(),
        "transcript_path": None,
        "last_assistant_message": None,
    }
    if prompt:
        temp = state_dir() / f"manual-{int(time.time())}.jsonl"
        temp.write_text(
            json.dumps({"message": {"role": "user", "content": prompt}}) + "\n",
            encoding="utf-8",
        )
        fake["transcript_path"] = str(temp)
    return handle_hook(fake)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claude-continuity")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("hook")
    worker_parser = sub.add_parser("worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("bundle")
    sub.add_parser("doctor")
    sub.add_parser("status")
    sub.add_parser("logs")
    manual_parser = sub.add_parser("manual")
    manual_parser.add_argument("prompt", nargs="?")
    args = parser.parse_args(argv)
    command = args.cmd or "hook"

    if command == "hook":
        try:
            return handle_hook(json.load(sys.stdin))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 0
    if command == "worker":
        return worker(pathlib.Path(args.bundle))
    if command == "doctor":
        return cmd_doctor()
    if command == "status":
        return cmd_status()
    if command == "logs":
        return cmd_logs()
    if command == "manual":
        return cmd_manual(args.prompt)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
