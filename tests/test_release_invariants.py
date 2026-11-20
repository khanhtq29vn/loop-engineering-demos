"""Release-facing invariants. No network, credentials or Docker daemon required."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from loopeng.backends import BackendError, OpenRouterChat, _NoRedirect
from loopeng.cli import main
from loopeng.core import InjectedInterruption
from loopeng.demo_se.pipeline import run as run_se
from loopeng.demo_se.fixtures import CANDIDATES
from loopeng.sandbox import verify


class ReleaseInvariantTests(unittest.TestCase):
    def test_modified_staged_file_is_never_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(InjectedInterruption):
                run_se(root, backend="offline", interrupt_on=1)
            run_id = next(root.glob("se-*/state.json")).parent.name
            staged = root / run_id / "candidates" / "ledger_attempt_01.py"
            staged.write_text("raise RuntimeError('do not run')\n", encoding="utf-8")
            _, state = run_se(root, backend="offline", resume_id=run_id)
            self.assertEqual(state["status"], "ESCALATED")
            self.assertEqual(state["details"]["stop_reason"], "CANDIDATE_INTEGRITY_MISMATCH")

    def test_offline_runner_only_accepts_immutable_reference_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(InjectedInterruption):
                run_se(root, backend="offline", interrupt_on=1)
            run_id = next(root.glob("se-*/state.json")).parent.name
            staged = root / run_id / "candidates" / "ledger_attempt_01.py"
            alternate = CANDIDATES[2]
            staged.write_text(alternate, encoding="utf-8")
            state_path = root / run_id / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            # Simulate a local checkpoint manipulated together with its checksum.
            from loopeng.core import sha256_file
            state["staged_sha256"] = sha256_file(staged)
            state_path.write_text(json.dumps(state), encoding="utf-8")
            _, end = run_se(root, backend="offline", resume_id=run_id)
            self.assertEqual(end["status"], "ABORTED")
            self.assertEqual(end["details"]["stop_reason"], "TRUSTED_LOCAL_FIXTURE_MISMATCH")

    def test_library_level_local_verifier_rejects_untrusted_code(self):
        from loopeng.sandbox import ExecutionError

        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "ledger.py"
            candidate.write_text("import os\nprint('not a fixture')\n", encoding="utf-8")
            with patch("loopeng.sandbox.subprocess.run") as process:
                with self.assertRaisesRegex(ExecutionError, "trusted_local"):
                    verify(candidate, "public", "trusted_local")
                process.assert_not_called()

    def test_untrusted_source_never_runs_trusted_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "SECURITY POLICY"):
                run_se(Path(tmp), backend="openrouter", sandbox="trusted_local")

    def test_docker_launch_has_isolation_flags(self):
        import subprocess
        candidate_dir = tempfile.TemporaryDirectory()
        self.addCleanup(candidate_dir.cleanup)
        source = Path(candidate_dir.name) / "ledger.py"
        source.write_text(CANDIDATES[2], encoding="utf-8")
        captured = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(command, 0, stdout='{"outcomes":[]}', stderr='')

        with patch("loopeng.sandbox.shutil.which", return_value="/usr/bin/docker"), \
             patch("loopeng.sandbox.subprocess.run", side_effect=fake_run):
            report = verify(source, "public", "docker")
        self.assertFalse(report["passed"])
        command = captured[0]
        for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--pids-limit=48", "--memory=256m", "--security-opt=no-new-privileges"):
            self.assertIn(flag, command)
        self.assertNotIn("OPENROUTER_API_KEY", " ".join(command))

    def test_preflight_without_credentials_fails_without_network(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "", "OPENROUTER_MODEL": ""}):
            with self.assertRaises(BackendError):
                OpenRouterChat()

    def test_referer_must_be_https(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-token", "OPENROUTER_MODEL": "test/model", "OPENROUTER_HTTP_REFERER": "http://test.invalid/"}):
            with self.assertRaises(BackendError):
                OpenRouterChat()._headers()

    def test_redirect_blocked(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://untrusted.test"))

    def test_cli_nonaccepted_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("sys.stdout"):
                code = main(["se", "--backend", "offline", "--max-attempts", "1", "--out", tmp])
            self.assertEqual(code, 4)

    def test_cli_governed_success_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("sys.stdout"):
                code = main(["se", "--backend", "offline", "--max-attempts", "3", "--out", tmp])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
