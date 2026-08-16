import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

import install


class InstallerSmokeTests(unittest.TestCase):
    def test_install_copies_complete_runtime_and_writes_launchers_and_hooks(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = pathlib.Path(tempdir)
            install_dir = root / "app"
            bin_dir = install_dir / "bin"
            claude_dir = root / ".claude"
            settings = claude_dir / "settings.json"
            fake_claude = root / "real-claude.exe"
            fake_claude.write_bytes(b"fake")

            with mock.patch.object(install, "INSTALL_DIR", install_dir), \
                 mock.patch.object(install, "BIN_DIR", bin_dir), \
                 mock.patch.object(install, "CLAUDE_DIR", claude_dir), \
                 mock.patch.object(install, "SETTINGS", settings), \
                 mock.patch.object(install, "find_real_claude", return_value=str(fake_claude)), \
                 mock.patch.object(install, "find_ollama_windows", return_value=None), \
                 mock.patch.object(install, "ensure_user_path_windows"), \
                 mock.patch.dict(os.environ, {"CLAUDE_CONTINUITY_COMMIT": "a" * 40}, clear=False):
                self.assertEqual(install.main(), 0)

            for name in install.RUNTIME_FILES:
                self.assertTrue((install_dir / name).exists(), name)
            self.assertTrue((bin_dir / "claude.cmd").exists())
            self.assertTrue((bin_dir / "claude-continuity.cmd").exists())

            launcher = (bin_dir / "claude-continuity.cmd").read_text(encoding="utf-8")
            self.assertIn("control.py", launcher)
            self.assertIn("%*", launcher)

            data = json.loads(settings.read_text(encoding="utf-8"))
            hooks = data["hooks"]
            self.assertIn("StopFailure", hooks)
            self.assertIn("Stop", hooks)
            self.assertIn("UserPromptSubmit", hooks)

            config = json.loads((install_dir / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["installed_commit"], "a" * 40)
            self.assertEqual(config["version"], install.PACKAGE_VERSION)


if __name__ == "__main__":
    unittest.main()
