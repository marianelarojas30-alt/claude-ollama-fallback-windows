import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("supervisor_hook", ROOT / "supervisor_hook.py")
hook = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(hook)


class SupervisorHookTests(unittest.TestCase):
    def test_rate_limit_requests_fallback(self):
        with tempfile.TemporaryDirectory() as tempdir:
            payload = {
                "hook_event_name": "StopFailure",
                "error": "rate_limit",
                "session_id": "abc123",
                "cwd": tempdir,
            }
            with mock.patch.dict(os.environ, {
                "CLAUDE_CONTINUITY_SUPERVISED": "1",
                "CLAUDE_CONTINUITY_PROVIDER": "anthropic",
                "CLAUDE_CONTINUITY_CONTROL_DIR": tempdir,
            }, clear=False):
                self.assertEqual(hook.handle(payload), 0)
            data = json.loads((pathlib.Path(tempdir) / "fallback-request.json").read_text())
            self.assertEqual(data["session_id"], "abc123")

    def test_stop_marks_ollama_idle(self):
        with tempfile.TemporaryDirectory() as tempdir:
            with mock.patch.dict(os.environ, {
                "CLAUDE_CONTINUITY_SUPERVISED": "1",
                "CLAUDE_CONTINUITY_PROVIDER": "ollama",
                "CLAUDE_CONTINUITY_CONTROL_DIR": tempdir,
            }, clear=False):
                hook.handle({"hook_event_name": "Stop", "session_id": "abc123", "cwd": tempdir})
            self.assertTrue((pathlib.Path(tempdir) / "fallback-idle.json").exists())

    def test_user_prompt_clears_idle(self):
        with tempfile.TemporaryDirectory() as tempdir:
            idle = pathlib.Path(tempdir) / "fallback-idle.json"
            idle.write_text("{}")
            with mock.patch.dict(os.environ, {
                "CLAUDE_CONTINUITY_SUPERVISED": "1",
                "CLAUDE_CONTINUITY_PROVIDER": "ollama",
                "CLAUDE_CONTINUITY_CONTROL_DIR": tempdir,
            }, clear=False):
                hook.handle({"hook_event_name": "UserPromptSubmit"})
            self.assertFalse(idle.exists())

    def test_probe_is_ignored(self):
        with tempfile.TemporaryDirectory() as tempdir:
            with mock.patch.dict(os.environ, {
                "CLAUDE_CONTINUITY_PROBE": "1",
                "CLAUDE_CONTINUITY_SUPERVISED": "1",
                "CLAUDE_CONTINUITY_PROVIDER": "anthropic",
                "CLAUDE_CONTINUITY_CONTROL_DIR": tempdir,
            }, clear=False):
                hook.handle({"hook_event_name": "StopFailure", "error": "rate_limit"})
            self.assertFalse((pathlib.Path(tempdir) / "fallback-request.json").exists())


if __name__ == "__main__":
    unittest.main()
