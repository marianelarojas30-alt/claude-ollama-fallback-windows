import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("continuity", ROOT / "continuity.py")
continuity = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(continuity)


class ContinuityTests(unittest.TestCase):
    def test_default_errors(self):
        self.assertTrue(continuity.allowed_error("rate_limit"))
        self.assertTrue(continuity.allowed_error("server_error"))
        self.assertTrue(continuity.allowed_error("billing_error"))
        self.assertTrue(continuity.allowed_error("max_output_tokens"))
        self.assertFalse(continuity.allowed_error("authentication_failed"))
        self.assertFalse(continuity.allowed_error("overloaded"))

    def test_prompt_contains_continuity_goal(self):
        prompt = continuity.build_prompt({"cwd": "C:/repo", "error": "rate_limit"})
        self.assertIn("Continue the unfinished work", prompt)
        self.assertIn("Preserve existing user changes", prompt)

    def test_transcript_extraction(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = pathlib.Path(tempdir) / "transcript.jsonl"
            path.write_text(
                json.dumps({"message": {"role": "user", "content": "finish feature"}}) + "\n",
                encoding="utf-8",
            )
            self.assertIn("finish feature", continuity.extract_transcript(str(path)))

    def test_safe_slug(self):
        self.assertEqual(continuity.safe_slug("abc / def"), "abc-def")


if __name__ == "__main__":
    unittest.main()
