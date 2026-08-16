import json
import pathlib
import tempfile
import unittest
from unittest import mock

import control


class WindowsHookVerificationTests(unittest.TestCase):
    def test_hook_configured_accepts_windows_backslash_paths(self):
        with tempfile.TemporaryDirectory() as tempdir:
            home = pathlib.Path(tempdir) / "home"
            install_dir = pathlib.Path(tempdir) / "AppData" / "Local" / "claude-ollama-continuity"
            settings = home / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            marker = str(install_dir / "supervisor_hook.py")
            data = {
                "hooks": {
                    "StopFailure": [{"hooks": [{"type": "command", "args": [marker]}]}],
                    "Stop": [{"hooks": [{"type": "command", "args": [marker]}]}],
                    "UserPromptSubmit": [{"hooks": [{"type": "command", "args": [marker]}]}],
                }
            }
            settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
            with mock.patch.object(control.pathlib.Path, "home", return_value=home), \
                 mock.patch.object(control.runtime, "install_dir", return_value=install_dir):
                ok, detail = control._hook_configured()
            self.assertTrue(ok, detail)
            self.assertIn("configured", detail)


if __name__ == "__main__":
    unittest.main()
