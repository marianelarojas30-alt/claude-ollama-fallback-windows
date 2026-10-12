import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import continuity


@unittest.skipUnless(shutil.which("git") and os.name == "posix", "POSIX fsmonitor fixture")
class RepositoryInspectionTests(unittest.TestCase):
    def test_snapshot_does_not_execute_repository_fsmonitor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            (root / "tracked.txt").write_text("synthetic fixture")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            marker = root / "HOOK_EXECUTED"
            hook = root / "monitor.sh"
            hook.write_text("#!/bin/sh\nprintf touched > HOOK_EXECUTED\nprintf 'token\\0'\n")
            hook.chmod(0o700)
            subprocess.run(["git", "config", "core.fsmonitor", str(hook)], cwd=root, check=True)
            snapshot = continuity.git_snapshot(directory)
            self.assertIn("git status", snapshot)
            self.assertFalse(marker.exists(), "Inspection executed a repository-configured hook")
