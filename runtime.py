#!/usr/bin/env python3
"""Runtime utilities for the Windows Claude Code <-> Ollama supervisor."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
from typing import Any

APP = "claude-ollama-continuity"
DEFAULT_MODEL = os.environ.get("CLAUDE_OLLAMA_MODEL", "qwen3.5")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def install_dir() -> pathlib.Path:
    if os.name == "nt":
        local = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home() / "AppData" / "Local"))
        return local / APP
    return pathlib.Path.home() / ".local" / "share" / APP


def state_dir() -> pathlib.Path:
    override = os.environ.get("CLAUDE_OLLAMA_STATE_DIR")
    if override:
        root = pathlib.Path(override).expanduser()
    elif os.name == "nt":
        root = install_dir() / "state"
    else:
        root = pathlib.Path.home() / ".local" / "state" / APP
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_json(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def config() -> dict[str, Any]:
    return read_json(install_dir() / "config.json") or {}


def normalize_exec(cmd: list[str]) -> list[str]:
    if os.name == "nt" and cmd:
        suffix = pathlib.Path(cmd[0]).suffix.lower()
        if suffix in {".cmd", ".bat"}:
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", *cmd]
    return cmd


def run_capture(cmd: list[str], cwd: str | None = None, timeout: int = 20, env: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            normalize_exec(cmd),
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)


def real_claude_executable() -> str | None:
    env_value = os.environ.get("CLAUDE_REAL_EXE")
    if env_value and pathlib.Path(env_value).exists():
        return env_value
    candidate = str(config().get("real_claude") or "")
    if candidate and pathlib.Path(candidate).exists():
        return candidate
    return None


def ollama_executable() -> str | None:
    env_value = os.environ.get("CLAUDE_OLLAMA_EXE")
    if env_value and pathlib.Path(env_value).exists():
        return env_value
    candidate = str(config().get("ollama_exe") or "")
    if candidate and pathlib.Path(candidate).exists():
        return candidate
    which = shutil.which("ollama")
    if which:
        return which
    if os.name == "nt":
        local = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home() / "AppData" / "Local"))
        candidates = [
            local / "Programs" / "Ollama" / "ollama.exe",
            local / "Ollama" / "ollama.exe",
            pathlib.Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe",
        ]
        for path in candidates:
            if path.exists():
                return str(path)
    return None


def claude_available() -> tuple[bool, str]:
    exe = real_claude_executable()
    if not exe:
        return False, "Real Claude Code executable is not configured"
    code, out = run_capture([exe, "--version"])
    return code == 0, out or f"exit code {code}"


def ollama_available() -> tuple[bool, str]:
    exe = ollama_executable()
    if not exe:
        return False, "Ollama executable was not found"
    code, out = run_capture([exe, "list"])
    return code == 0, out or f"exit code {code}"


def installed_models() -> tuple[bool, list[str], str]:
    exe = ollama_executable()
    if not exe:
        return False, [], "Ollama executable was not found"
    code, out = run_capture([exe, "list"])
    if code != 0:
        return False, [], out or f"exit code {code}"
    names: list[str] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if parts:
            names.append(parts[0])
    return True, names, out


def model_available(model: str) -> tuple[bool, str]:
    ok, names, detail = installed_models()
    if not ok:
        return False, detail
    base = model.split(":", 1)[0]
    for name in names:
        if name == model or name.split(":", 1)[0] == base:
            return True, f"{model} is installed"
    return False, f"{model} is not installed"


def pull_model(model: str) -> tuple[bool, int]:
    exe = ollama_executable()
    if not exe:
        return False, 127
    try:
        proc = subprocess.run(normalize_exec([exe, "pull", model]), check=False)
        return proc.returncode == 0, proc.returncode
    except OSError:
        return False, 127


def fallback_environment(control: pathlib.Path) -> dict[str, str]:
    env = os.environ.copy()
    real = real_claude_executable()
    if real:
        env["CLAUDE_REAL_EXE"] = real
    ollama = ollama_executable()
    if ollama:
        env["CLAUDE_OLLAMA_EXE"] = ollama
    env["CLAUDE_CONTINUITY_INTERNAL"] = "1"
    env["CLAUDE_CONTINUITY_SUPERVISED"] = "1"
    env["CLAUDE_CONTINUITY_PROVIDER"] = "ollama"
    env["CLAUDE_CONTINUITY_CONTROL_DIR"] = str(control)
    env["CLAUDE_OLLAMA_FALLBACK_ACTIVE"] = "1"
    env["ANTHROPIC_AUTH_TOKEN"] = "ollama"
    env["ANTHROPIC_API_KEY"] = ""
    env["ANTHROPIC_BASE_URL"] = os.environ.get("CLAUDE_OLLAMA_BASE_URL", "http://localhost:11434")
    return env


def primary_environment(control: pathlib.Path) -> dict[str, str]:
    env = os.environ.copy()
    real = real_claude_executable()
    if real:
        env["CLAUDE_REAL_EXE"] = real
    ollama = ollama_executable()
    if ollama:
        env["CLAUDE_OLLAMA_EXE"] = ollama
    env["CLAUDE_CONTINUITY_INTERNAL"] = "1"
    env["CLAUDE_CONTINUITY_SUPERVISED"] = "1"
    env["CLAUDE_CONTINUITY_PROVIDER"] = "anthropic"
    env["CLAUDE_CONTINUITY_CONTROL_DIR"] = str(control)
    env.pop("CLAUDE_OLLAMA_FALLBACK_ACTIVE", None)
    if env.get("ANTHROPIC_AUTH_TOKEN") == "ollama":
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    if env.get("ANTHROPIC_API_KEY") == "":
        env.pop("ANTHROPIC_API_KEY", None)
    if env.get("ANTHROPIC_BASE_URL", "").rstrip("/") in {"http://localhost:11434", "http://127.0.0.1:11434"}:
        env.pop("ANTHROPIC_BASE_URL", None)
    return env
