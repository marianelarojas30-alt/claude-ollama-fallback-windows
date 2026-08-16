import json
import pathlib
import tempfile
import unittest
from unittest import mock

import continuity


class ContinuityUtilityTests(unittest.TestCase):
    def test_transcript_extraction(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = pathlib.Path(tempdir) / "transcript.jsonl"
            path.write_text(
                json.dumps({"message": {"role": "user", "content": "finish feature"}}) + "\n"
                + json.dumps({"message": {"role": "assistant", "content": "working on it"}}) + "\n",
                encoding="utf-8",
            )
            text = continuity.extract_transcript(str(path))
            self.assertIn("finish feature", text)
            self.assertIn("working on it", text)

    def test_missing_transcript_is_nonfatal(self):
        text = continuity.extract_transcript("Z:/definitely-missing.jsonl")
        self.assertIn("Transcript not found", text)

    def test_git_snapshot_is_nonfatal_without_git(self):
        with mock.patch.object(continuity.shutil, "which", return_value=None):
            self.assertEqual(continuity.git_snapshot("."), "git not installed")


if __name__ == "__main__":
    unittest.main()
