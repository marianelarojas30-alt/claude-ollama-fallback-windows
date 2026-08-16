import json
import os
import pathlib
import tempfile
import time
import unittest
from unittest import mock

import control
import runtime
import supervisor
import supervisor_hook


class SupervisorBehaviorTests(unittest.TestCase):
    def test_primary_starts_without_checking_ollama(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state = pathlib.Path(tempdir) / "state"
            cwd = pathlib.Path(tempdir) / "repo"
            cwd.mkdir()
            with mock.patch.object(supervisor.runtime, "state_dir", return_value=state), \
                 mock.patch.object(supervisor, "run_primary", return_value=("exit", None, None, 0)) as primary, \
                 mock.patch.object(supervisor, "run_ollama") as fallback, \
                 mock.patch.object(supervisor.runtime, "ollama_available", side_effect=AssertionError("startup must not check Ollama")):
                self.assertEqual(supervisor.supervise(str(cwd), []), 0)
                primary.assert_called_once()
                fallback.assert_not_called()

    def test_fallback_readiness_requires_ollama_only_when_called(self):
        with mock.patch.object(supervisor.runtime, "ollama_available", return_value=(False, "missing")), \
             mock.patch.object(supervisor.runtime, "model_available") as model:
            ok, detail = supervisor.fallback_readiness("qwen3.5")
            self.assertFalse(ok)
            self.assertEqual(detail, "missing")
            model.assert_not_called()

    def test_primary_environment_clears_ollama_provider_variables(self):
        with tempfile.TemporaryDirectory() as tempdir:
            control_dir = pathlib.Path(tempdir)
            with mock.patch.dict(os.environ, {
                "ANTHROPIC_AUTH_TOKEN": "ollama",
                "ANTHROPIC_API_KEY": "",
                "ANTHROPIC_BASE_URL": "http://localhost:11434",
            }, clear=False), mock.patch.object(runtime, "real_claude_executable", return_value="C:/claude.exe"), mock.patch.object(runtime, "ollama_executable", return_value="C:/ollama.exe"):
                env = runtime.primary_environment(control_dir)
                self.assertNotEqual(env.get("ANTHROPIC_AUTH_TOKEN"), "ollama")
                self.assertNotIn("ANTHROPIC_BASE_URL", env)
                self.assertEqual(env["CLAUDE_CONTINUITY_PROVIDER"], "anthropic")

    def test_control_ignores_stale_supervisor_directories(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(os.environ, {"LOCALAPPDATA": tempdir}, clear=False):
            root = control.state_dir() / "supervisor"
            stale = root / "111"
            live = root / "222"
            stale.mkdir(parents=True)
            live.mkdir(parents=True)
            (stale / "heartbeat.json").write_text(json.dumps({"epoch": time.time() - 60}), encoding="utf-8")
            (live / "heartbeat.json").write_text(json.dumps({"epoch": time.time()}), encoding="utf-8")
            self.assertEqual(control.active_control(), live)

    def test_ollama_command_never_resumes_anthropic_session(self):
        with mock.patch.object(supervisor, "real_claude", return_value="C:/claude.exe"):
            cmd = supervisor.build_ollama_command("qwen3.5", "acceptEdits", "handoff prompt")
        self.assertEqual(cmd[0], "C:/claude.exe")
        self.assertIn("qwen3.5", cmd)
        self.assertNotIn("--resume", cmd)
        self.assertIn("handoff prompt", cmd)

    def test_primary_resume_uses_original_session_and_handback(self):
        with mock.patch.object(supervisor, "real_claude", return_value="C:/claude.exe"):
            cmd = supervisor.build_primary_command("anthropic-session-123", [], "fallback finished")
        self.assertEqual(cmd[:3], ["C:/claude.exe", "--resume", "anthropic-session-123"])
        self.assertEqual(cmd[-1], "fallback finished")
        self.assertNotIn("qwen3.5", cmd)

    def test_fallback_prompt_uses_transcript_and_repo_not_resume(self):
        with mock.patch.object(supervisor.continuity, "extract_transcript", return_value="RECENT CHAT"), \
             mock.patch.object(supervisor.continuity, "git_snapshot", return_value="GIT STATE"):
            prompt = supervisor.fallback_prompt("C:/repo", {
                "error": "rate_limit",
                "error_details": "429",
                "transcript_path": "C:/transcript.jsonl",
                "session_id": "anthropic-session-123",
            })
        self.assertIn("RECENT CHAT", prompt)
        self.assertIn("GIT STATE", prompt)
        self.assertIn("separate Ollama-backed Claude Code session", prompt)

    def test_simulated_recovery_does_not_force_immediate_return_signal(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(os.environ, {"LOCALAPPDATA": tempdir}, clear=False):
            root = control.state_dir() / "supervisor" / "222"
            root.mkdir(parents=True)
            (root / "heartbeat.json").write_text(json.dumps({"epoch": time.time()}), encoding="utf-8")
            self.assertEqual(control.simulate_recovery(), 0)
            self.assertTrue((root / "primary-ready.json").exists())
            self.assertFalse((root / "return-request.json").exists())


class HookBehaviorTests(unittest.TestCase):
    def test_rate_limit_creates_fallback_signal(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(os.environ, {
            "CLAUDE_CONTINUITY_SUPERVISED": "1",
            "CLAUDE_CONTINUITY_PROVIDER": "anthropic",
            "CLAUDE_CONTINUITY_CONTROL_DIR": tempdir,
        }, clear=False):
            supervisor_hook.handle({
                "hook_event_name": "StopFailure",
                "session_id": "abc",
                "cwd": tempdir,
                "error": "rate_limit",
                "error_details": "429",
            })
            signal = pathlib.Path(tempdir) / "fallback-request.json"
            self.assertTrue(signal.exists())
            payload = json.loads(signal.read_text(encoding="utf-8"))
            self.assertEqual(payload["session_id"], "abc")
            self.assertEqual(payload["error"], "rate_limit")

    def test_non_official_overloaded_value_does_not_trigger(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(os.environ, {
            "CLAUDE_CONTINUITY_SUPERVISED": "1",
            "CLAUDE_CONTINUITY_PROVIDER": "anthropic",
            "CLAUDE_CONTINUITY_CONTROL_DIR": tempdir,
        }, clear=False):
            supervisor_hook.handle({"hook_event_name": "StopFailure", "error": "overloaded"})
            self.assertFalse((pathlib.Path(tempdir) / "fallback-request.json").exists())


if __name__ == "__main__":
    unittest.main()
