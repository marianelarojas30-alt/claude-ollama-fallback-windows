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

    def test_fallback_readiness_checks_ollama_only_when_needed(self):
        with mock.patch.object(supervisor.runtime, "ollama_available", return_value=(False, "missing")), \
             mock.patch.object(supervisor.runtime, "model_available") as model:
            ok, detail = supervisor.fallback_readiness("qwen3.5")
            self.assertFalse(ok)
            self.assertEqual(detail, "missing")
            model.assert_not_called()

    def test_probe_marks_itself_so_hooks_cannot_overwrite_session(self):
        stop = mock.Mock()
        stop.wait.side_effect = [False, True]
        completed = mock.Mock(returncode=0)
        with tempfile.TemporaryDirectory() as tempdir, \
             mock.patch.object(supervisor.runtime, "state_dir", return_value=pathlib.Path(tempdir)), \
             mock.patch.object(supervisor, "real_claude", return_value="claude.exe"), \
             mock.patch.object(supervisor, "child_env", return_value={}), \
             mock.patch.object(supervisor.subprocess, "run", return_value=completed) as run:
            supervisor.probe_primary(pathlib.Path(tempdir), stop)
            env = run.call_args.kwargs["env"]
            self.assertEqual(env["CLAUDE_CONTINUITY_PROBE"], "1")

    def test_fast_primary_exit_still_consumes_stopfailure_signal(self):
        request = {"session_id": "abc", "error": "rate_limit"}
        fake_proc = mock.Mock()
        fake_proc.poll.return_value = 1
        fake_proc.returncode = 1
        with tempfile.TemporaryDirectory() as tempdir, \
             mock.patch.object(supervisor, "build_primary_command", return_value=["claude.exe"]), \
             mock.patch.object(supervisor, "spawn_visible", return_value=fake_proc), \
             mock.patch.object(supervisor, "fallback_from_signal", side_effect=[(request, "abc")]):
            action, payload, session, code = supervisor.run_primary(tempdir, pathlib.Path(tempdir), None, [])
            self.assertEqual(action, "fallback")
            self.assertEqual(payload["error"], "rate_limit")
            self.assertEqual(session, "abc")
            self.assertEqual(code, 0)

    def test_ollama_command_never_resumes_anthropic_session(self):
        with mock.patch.object(supervisor, "real_claude", return_value="C:/claude.exe"):
            cmd = supervisor.build_ollama_command("qwen3.5", "acceptEdits", "handoff prompt")
        self.assertEqual(cmd[0], "C:/claude.exe")
        self.assertIn("qwen3.5", cmd)
        self.assertNotIn("--resume", cmd)
        self.assertIn("handoff prompt", cmd)

    def test_primary_resume_uses_only_original_anthropic_session(self):
        with mock.patch.object(supervisor, "real_claude", return_value="C:/claude.exe"):
            cmd = supervisor.build_primary_command("anthropic-123", [], "fallback finished")
        self.assertEqual(cmd[:3], ["C:/claude.exe", "--resume", "anthropic-123"])
        self.assertEqual(cmd[-1], "fallback finished")
        self.assertNotIn("qwen3.5", cmd)

    def test_permission_mode_inherits_from_primary_request(self):
        self.assertEqual(supervisor.resolved_permission_mode({"permission_mode": "plan"}), "plan")
        with mock.patch.dict(os.environ, {"CLAUDE_OLLAMA_PERMISSION_MODE": "acceptEdits"}, clear=False):
            self.assertEqual(supervisor.resolved_permission_mode({"permission_mode": "plan"}), "acceptEdits")

    def test_model_check_does_not_accept_wrong_tag(self):
        with mock.patch.object(runtime, "installed_models", return_value=(True, ["qwen3.5:0.8b"], "")):
            ok, _ = runtime.model_available("qwen3.5")
            self.assertFalse(ok)
        with mock.patch.object(runtime, "installed_models", return_value=(True, ["qwen3.5:latest"], "")):
            ok, _ = runtime.model_available("qwen3.5")
            self.assertTrue(ok)


class ControlBehaviorTests(unittest.TestCase):
    def _live(self, root: pathlib.Path, pid: str, cwd: str) -> pathlib.Path:
        path = root / pid
        path.mkdir(parents=True)
        (path / "heartbeat.json").write_text(json.dumps({"pid": int(pid), "cwd": cwd, "epoch": time.time()}), encoding="utf-8")
        (path / "supervisor.json").write_text(json.dumps({"pid": int(pid), "cwd": cwd}), encoding="utf-8")
        return path

    def test_stale_supervisor_is_ignored(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(os.environ, {"LOCALAPPDATA": tempdir}, clear=False):
            root = control.state_dir() / "supervisor"
            stale = root / "111"
            stale.mkdir(parents=True)
            (stale / "heartbeat.json").write_text(json.dumps({"epoch": time.time() - 60}), encoding="utf-8")
            live = self._live(root, "222", "C:/repo")
            self.assertEqual(control.active_control(), live)

    def test_multiple_live_sessions_refuse_to_guess(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(os.environ, {"LOCALAPPDATA": tempdir}, clear=False):
            root = control.state_dir() / "supervisor"
            self._live(root, "111", "C:/one")
            self._live(root, "222", "C:/two")
            with self.assertRaises(SystemExit):
                control.active_control()
            self.assertEqual(control.active_control(222).name, "222")

    def test_simulated_recovery_waits_for_safe_stop(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(os.environ, {"LOCALAPPDATA": tempdir}, clear=False):
            root = control.state_dir() / "supervisor"
            live = self._live(root, "222", "C:/repo")
            self.assertEqual(control.simulate_recovery(222), 0)
            self.assertTrue((live / "primary-ready.json").exists())
            self.assertFalse((live / "return-request.json").exists())


class HookBehaviorTests(unittest.TestCase):
    def test_rate_limit_creates_fallback_signal_with_permission_mode(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(os.environ, {
            "CLAUDE_CONTINUITY_SUPERVISED": "1",
            "CLAUDE_CONTINUITY_PROVIDER": "anthropic",
            "CLAUDE_CONTINUITY_CONTROL_DIR": tempdir,
        }, clear=False):
            supervisor_hook.handle({
                "hook_event_name": "StopFailure",
                "session_id": "abc",
                "cwd": tempdir,
                "permission_mode": "plan",
                "error": "rate_limit",
                "error_details": "429",
            })
            signal = pathlib.Path(tempdir) / "fallback-request.json"
            self.assertTrue(signal.exists())
            payload = json.loads(signal.read_text(encoding="utf-8"))
            self.assertEqual(payload["session_id"], "abc")
            self.assertEqual(payload["error"], "rate_limit")
            self.assertEqual(payload["permission_mode"], "plan")

    def test_probe_events_are_ignored(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(os.environ, {
            "CLAUDE_CONTINUITY_SUPERVISED": "1",
            "CLAUDE_CONTINUITY_PROVIDER": "anthropic",
            "CLAUDE_CONTINUITY_CONTROL_DIR": tempdir,
            "CLAUDE_CONTINUITY_PROBE": "1",
        }, clear=False):
            supervisor_hook.handle({"hook_event_name": "Stop", "session_id": "probe"})
            self.assertFalse((pathlib.Path(tempdir) / "current-session.json").exists())

    def test_non_supported_error_does_not_trigger(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(os.environ, {
            "CLAUDE_CONTINUITY_SUPERVISED": "1",
            "CLAUDE_CONTINUITY_PROVIDER": "anthropic",
            "CLAUDE_CONTINUITY_CONTROL_DIR": tempdir,
        }, clear=False):
            supervisor_hook.handle({"hook_event_name": "StopFailure", "error": "invalid_request"})
            self.assertFalse((pathlib.Path(tempdir) / "fallback-request.json").exists())


if __name__ == "__main__":
    unittest.main()
