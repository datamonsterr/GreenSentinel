import json
import sys
import tempfile
import unittest
from pathlib import Path

# Locate repository root containing pyproject.toml to dynamically resolve scripts directory
_current_path = Path(__file__).resolve()
_project_root = next(
    (p for p in _current_path.parents if (p / "pyproject.toml").exists()),
    _current_path.parent,
)
scripts_dir = str(_project_root / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

import log_codex as m  # noqa: E402


class CollectorTest(unittest.TestCase):
    def test_recovery_scope_and_dedup_after_archive(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            sessions = root / "sessions"
            sessions.mkdir()
            logs = root / "logs"

            def write(name, cwd):
                rows = [
                    {"type": "session_meta", "payload": {"id": name, "cwd": str(cwd)}},
                    {
                        "type": "response_item",
                        "timestamp": "2026-09-15T01:00:00Z",
                        "payload": {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "<environment_context>injected</environment_context>"}
                            ],
                        },
                    },
                    {
                        "type": "response_item",
                        "timestamp": "2026-09-15T01:01:00Z",
                        "payload": {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "learn "},
                                {"type": "input_text", "text": "LangGraph"},
                            ],
                        },
                    },
                ]
                (sessions / name).write_text("".join(json.dumps(r) + "\n" for r in rows))

            # Explicit repo root: collect() chdirs, and other tests can change Path.cwd() under xdist.
            write("a.jsonl", m.ROOT)
            write("b.jsonl", root / "other")
            self.assertEqual(m.collect(sessions, logs), 1)
            entry = json.loads((logs / "session.jsonl").read_text())
            self.assertEqual(entry["prompt"], "learn LangGraph")
            self.assertEqual(m.collect(sessions, logs), 0)
            (logs / "archive").mkdir()
            (logs / "session.jsonl").rename(logs / "archive" / "today.jsonl")
            self.assertEqual(m.collect(sessions, logs), 0)


if __name__ == "__main__":
    unittest.main()


class SubmissionTest(unittest.TestCase):
    def test_http_success_archives_real_batch(self):
        self.run_submission(False)

    def test_http_failure_preserves_batch(self):
        self.run_submission(True)

    def run_submission(self, fail):
        import urllib.error
        from unittest.mock import MagicMock, patch

        import submit_log as submit

        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            live = root / "session.jsonl"
            live.write_text('{"prompt":"synthetic test"}\n')
            response = MagicMock()
            response.__enter__.return_value.status = 200
            with (
                patch.multiple(
                    submit,
                    SERVER_URL="https://example.invalid/log",
                    LOG_DIR=root,
                    LOG_FILE=live,
                    ARCHIVE_DIR=root / "archive",
                ),
                patch("log_codex.collect", return_value=0),
                patch.object(
                    submit.urllib.request,
                    "urlopen",
                    side_effect=urllib.error.URLError("offline") if fail else None,
                    return_value=response,
                ),
            ):
                if fail:
                    with self.assertRaises(SystemExit):
                        submit.main()
                    self.assertIn("synthetic test", live.read_text())
                else:
                    submit.main()
                    self.assertFalse(live.exists())
                    self.assertEqual(len(list((root / "archive").glob("*.jsonl"))), 1)
