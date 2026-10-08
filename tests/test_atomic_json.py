import json
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import install  # noqa: E402
import runtime  # noqa: E402
import updater  # noqa: E402


class WriteJsonAtomicTests(unittest.TestCase):
    def test_writes_and_replaces(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "sub" / "a.json"
            runtime.write_json_atomic(p, {"x": 1})
            runtime.write_json_atomic(p, {"x": 2}, trailing_newline=True)
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"x": 2})
            self.assertTrue(p.read_text(encoding="utf-8").endswith("\n"))
            self.assertEqual([c.name for c in p.parent.iterdir()], ["a.json"])

    def test_concurrent_writers_never_leave_partial_or_temp_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "signal.json"
            errors = []

            def writer(n):
                try:
                    for i in range(50):
                        runtime.write_json_atomic(p, {"writer": n, "i": i, "pad": "x" * 2000})
                except Exception as exc:  # pragma: no cover - reported below
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            self.assertIn("writer", json.loads(p.read_text(encoding="utf-8")))
            self.assertEqual([c.name for c in p.parent.iterdir()], ["signal.json"])

    def test_failure_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "a.json"
            with mock.patch.object(runtime.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    runtime.write_json_atomic(p, {"x": 1})
            self.assertEqual(list(pathlib.Path(d).iterdir()), [])


class FileListConsistencyTests(unittest.TestCase):
    def test_updater_downloads_exactly_the_files_install_requires(self):
        self.assertEqual(list(updater.FILES), list(install.RUNTIME_FILES))


if __name__ == "__main__":
    unittest.main()
