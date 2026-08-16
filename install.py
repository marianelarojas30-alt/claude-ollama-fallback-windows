#!/usr/bin/env python3
"""Installer for Claude Ollama Continuity."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys

APP = "claude-ollama-continuity"
PACKAGE_VERSION = "1.0.1"
ROOT = pathlib.Path(__file__).resolve().parent
HOME = pathlib.Path.home()
CLAUDE_DIR = HOME / ".claude"
SETTINGS = CLAUDE_DIR / "settings.json"
RUNTIME_FILES = (
    "continuity.py",
    "runtime.py",
    "supervisor.py",
    "supervisor_hook.py",
    "control.py",
    "install.py",
    "updater.py",
)

if os.name == "nt":
    LOCAL = pathlib.Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))
    INSTALL_DIR = LOCAL / APP
    BIN_DIR = INSTALL_DIR / "bin"
else:
    INSTALL_DIR = HOME / ".local" / "share" / APP
    BIN_DIR = HOME / ".local" / "bin"


def load_settings() -> dict:
    if not SETTINGS.exists():
        return {}
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {SETTINGS}: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"{SETTINGS} root must be a JSON object")
    return data


def atomic_write_json(path: pathlib.Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def existing_real_claude() -> str | None:
    config = INSTALL_DIR / "config.json"
    if config.exists():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            candidate = str(data.get("real_claude") or "")
            if candidate and pathlib.Path(candidate).exists():
                return candidate
        except Exception:
            pass
    return None


def find_real_claude() -> str:
    saved = existing_real_claude()
    if saved:
        return saved
    path_parts: list[str] = []
    for part in os.environ.get("PATH", "").split(os.pathsep):
        if not part:
            continue
        try:
            if pathlib.Path(part).resolve() == BIN_DIR.resolve():
                continue
        except OSError:
            pass
        path_parts.append(part)
    candidate = shutil.which("claude", path=os.pathsep.join(path_parts))
    if not candidate:
        raise SystemExit("Claude Code must already be installed before this continuity layer.")
    return str(pathlib.Path(candidate).resolve())


def find_ollama_windows() -> pathlib.Path | None:
    if os.name != "nt":
        value = shutil.which("ollama")
        return pathlib.Path(value) if value else None
    existing = shutil.which("ollama")
    if existing:
        return pathlib.Path(existing)
    candidates = [
        LOCAL / "Programs" / "Ollama" / "ollama.exe",
        LOCAL / "Ollama" / "ollama.exe",
        pathlib.Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _same_windows_path(left: str, right: str) -> bool:
    return os.path.normcase(left.strip().rstrip("\\/")) == os.path.normcase(right.strip().rstrip("\\/"))


def ensure_user_path_windows(directory: pathlib.Path) -> None:
    """Put *directory* first in the current process and persistent User PATH.

    This writes HKCU\\Environment\\Path directly with Python's winreg module.
    It deliberately does not shell out to PowerShell, avoiding command-line
    quoting/parsing failures for Windows paths.
    """
    if os.name != "nt":
        return

    target = str(directory)

    current = os.environ.get("PATH", "")
    current_entries = [entry for entry in current.split(";") if entry]
    if not any(_same_windows_path(entry, target) for entry in current_entries):
        os.environ["PATH"] = target + (";" + current if current else "")

    try:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            try:
                user_path, value_type = winreg.QueryValueEx(key, "Path")
                user_path = str(user_path or "")
            except FileNotFoundError:
                user_path = ""
                value_type = winreg.REG_EXPAND_SZ

            entries = [entry for entry in user_path.split(";") if entry]
            entries = [entry for entry in entries if not _same_windows_path(entry, target)]
            new_path = ";".join([target, *entries])

            if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                value_type = winreg.REG_EXPAND_SZ
            winreg.SetValueEx(key, "Path", 0, value_type, new_path)
    except OSError as exc:
        raise SystemExit(f"Could not update User PATH in HKCU\\Environment: {exc}") from exc


def remove_our_hooks(hooks: dict, marker: str) -> None:
    for event in ("StopFailure", "Stop", "UserPromptSubmit"):
        entries = hooks.get(event, [])
        kept = [entry for entry in entries if marker not in json.dumps(entry) and APP not in json.dumps(entry)]
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)


def add_hook(hooks: dict, event: str, target: pathlib.Path, matcher: str | None = None) -> None:
    entry: dict = {
        "hooks": [
            {
                "type": "command",
                "command": sys.executable,
                "args": [str(target)],
                "timeout": 10,
            }
        ]
    }
    if matcher is not None:
        entry["matcher"] = matcher
    hooks.setdefault(event, []).append(entry)


def write_launchers(real_claude: str) -> None:
    control = INSTALL_DIR / "control.py"
    supervisor = INSTALL_DIR / "supervisor.py"
    updater = INSTALL_DIR / "updater.py"

    if os.name == "nt":
        (BIN_DIR / "claude-continuity.cmd").write_text(
            f'@echo off\r\n'
            f'if /I "%~1"=="update" (\r\n  "{sys.executable}" "{updater}"\r\n  exit /b %ERRORLEVEL%\r\n)\r\n'
            f'"{sys.executable}" "{control}" %*\r\n',
            encoding="utf-8",
        )
        (BIN_DIR / "claude.cmd").write_text(
            f'@echo off\r\n'
            f'if "%CLAUDE_CONTINUITY_INTERNAL%"=="1" (\r\n  "{real_claude}" %*\r\n) else (\r\n  "{sys.executable}" "{supervisor}" --cwd "%CD%" -- %*\r\n)\r\n',
            encoding="utf-8",
        )
        ensure_user_path_windows(BIN_DIR)
    else:
        continuity_launcher = BIN_DIR / "claude-continuity"
        continuity_launcher.write_text(
            f'#!/bin/sh\nif [ "$1" = "update" ]; then exec "{sys.executable}" "{updater}"; fi\nexec "{sys.executable}" "{control}" "$@"\n',
            encoding="utf-8",
        )
        continuity_launcher.chmod(0o755)
        claude_launcher = BIN_DIR / "claude"
        claude_launcher.write_text(
            f'#!/bin/sh\nif [ "$CLAUDE_CONTINUITY_INTERNAL" = "1" ]; then exec "{real_claude}" "$@"; fi\nexec "{sys.executable}" "{supervisor}" --cwd "$PWD" -- "$@"\n',
            encoding="utf-8",
        )
        claude_launcher.chmod(0o755)


def verify_installed_runtime() -> None:
    missing = [name for name in RUNTIME_FILES if not (INSTALL_DIR / name).exists()]
    if missing:
        raise SystemExit("INSTALL VERIFY FAILED: missing " + ", ".join(missing))
    proc = subprocess.run(
        [sys.executable, "-c", "import continuity,runtime,supervisor,supervisor_hook,control; print('runtime import OK')"],
        cwd=str(INSTALL_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit("INSTALL VERIFY FAILED: " + (proc.stdout.strip() or "import error"))
    if os.name == "nt":
        for name in ("claude.cmd", "claude-continuity.cmd"):
            if not (BIN_DIR / name).exists():
                raise SystemExit(f"INSTALL VERIFY FAILED: missing launcher {name}")
    print("Runtime verification: OK")


def main() -> int:
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

    real_claude = find_real_claude()
    ollama_exe = find_ollama_windows()
    if ollama_exe is not None and os.name == "nt":
        ensure_user_path_windows(ollama_exe.parent)

    for name in RUNTIME_FILES:
        source = ROOT / name
        if not source.exists():
            raise SystemExit(f"Installer source missing required file: {name}")
        shutil.copy2(source, INSTALL_DIR / name)

    if os.name != "nt":
        for name in RUNTIME_FILES:
            path = INSTALL_DIR / name
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

    write_launchers(real_claude)

    data = load_settings()
    hooks = data.setdefault("hooks", {})
    hook_target = INSTALL_DIR / "supervisor_hook.py"
    remove_our_hooks(hooks, str(hook_target))
    add_hook(hooks, "StopFailure", hook_target, "rate_limit|billing_error|server_error|max_output_tokens")
    add_hook(hooks, "Stop", hook_target)
    add_hook(hooks, "UserPromptSubmit", hook_target)

    if SETTINGS.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = SETTINGS.with_name(f"settings.json.continuity-backup-{stamp}")
        shutil.copy2(SETTINGS, backup)
        print(f"Backup: {backup}")
    atomic_write_json(SETTINGS, data)

    atomic_write_json(
        INSTALL_DIR / "config.json",
        {
            "version": PACKAGE_VERSION,
            "installed_commit": os.environ.get("CLAUDE_CONTINUITY_COMMIT"),
            "real_claude": real_claude,
            "ollama_exe": str(ollama_exe) if ollama_exe else None,
            "repository": "marianelarojas30-alt/claude-ollama-fallback-windows",
        },
    )

    verify_installed_runtime()
    print("\nINSTALLED / UPDATED OK")
    print(f"Version:          {PACKAGE_VERSION}")
    print(f"Installed commit: {os.environ.get('CLAUDE_CONTINUITY_COMMIT') or '(local install)'}")
    print(f"Real Claude:      {real_claude}")
    print(f"Ollama:           {ollama_exe or '(not found yet)'}")
    print(f"Global wrapper:   {BIN_DIR / ('claude.cmd' if os.name == 'nt' else 'claude')}")
    print("\nOpen a NEW terminal, then run: claude-continuity self-test")
    print("Normal use after that: claude")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
