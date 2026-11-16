import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import install


class InstallerSmokeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "requires cmd.exe")
    def test_batch_setup_reports_the_installer_exit_status(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = pathlib.Path(tempdir)
            shutil.copyfile(install.ROOT / "INSTALL_WINDOWS.bat", root / "INSTALL_WINDOWS.bat")
            # Exercise the documented python.exe fallback, even on runners that have py.exe.
            system32 = pathlib.Path(os.environ["SystemRoot"]) / "System32"
            env = {**os.environ, "PATH": os.pathsep.join((str(pathlib.Path(sys.executable).parent), str(system32)))}
            for expected in (19, 0):
                with self.subTest(expected=expected):
                    (root / "install.py").write_text(f"raise SystemExit({expected})", encoding="utf-8")
                    result = subprocess.run(
                        [os.environ["COMSPEC"], "/d", "/c", "INSTALL_WINDOWS.bat"],
                        cwd=root, env=env, input=b"\n", capture_output=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                    self.assertEqual(b"Installation complete." in result.stdout, expected == 0)

    @unittest.skipUnless(os.name == "nt", "requires cmd.exe")
    def test_update_launcher_propagates_updater_failure(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = pathlib.Path(tempdir)
            with mock.patch.object(install, "INSTALL_DIR", root), \
                 mock.patch.object(install, "BIN_DIR", root), \
                 mock.patch.object(install, "ensure_user_path_windows"):
                install.write_launchers("unused")

            (root / "updater.py").write_text("raise SystemExit(23)", encoding="utf-8")
            result = subprocess.run(
                [os.environ["COMSPEC"], "/d", "/c", "claude-continuity.cmd", "update"],
                cwd=root, capture_output=True, timeout=30,
            )
            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)

    @unittest.skipUnless(os.name == "nt", "install.py writes the .cmd launchers only on Windows")
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
