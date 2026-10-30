from __future__ import annotations

import os
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import capability_broker


class CapabilityBrokerIsolationTests(unittest.TestCase):
    def test_verifier_invokes_each_checkout_test_by_its_absolute_file_path(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            sandbox = Path(temporary).resolve()
            test_path = "tests/unit/test_file_bridge.py"
            commands = capability_broker._test_file_commands([test_path], sandbox)

        self.assertEqual(commands, [[sys.executable, "-B", str(sandbox / test_path)]])

    def test_untracked_allowed_source_is_included_in_the_patch_candidate_set(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            checkout = Path(temporary)
            existing = checkout / "src" / "agent" / "existing.py"
            existing.parent.mkdir(parents=True)
            existing.write_text("value = 1\n", encoding="utf-8")
            for command in (
                ["git", "init", "-q", "-b", "main"],
                ["git", "config", "user.name", "Capability Test"],
                ["git", "config", "user.email", "capability-test@localhost"],
                ["git", "add", "."],
                ["git", "commit", "-q", "-m", "baseline"],
            ):
                subprocess.run(command, cwd=checkout, check=True, capture_output=True)

            existing.write_text("value = 2\n", encoding="utf-8")
            new_file = checkout / "src" / "agent" / "new_module.py"
            new_file.write_text("value = 3\n", encoding="utf-8")
            changed = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                cwd=checkout, check=True, capture_output=True, text=True).stdout.splitlines()
            untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                cwd=checkout, check=True, capture_output=True, text=True).stdout.splitlines()

            candidates = capability_broker._candidate_paths(changed, untracked)
            subprocess.run(["git", "add", "-N", "--", *untracked],
                cwd=checkout, check=True, capture_output=True)
            patch_text = subprocess.run(["git", "diff", "--binary", "HEAD", "--", *candidates],
                cwd=checkout, check=True, capture_output=True, text=True).stdout

        self.assertIn("src/agent/new_module.py", candidates)
        self.assertIn("src/agent/new_module.py", patch_text)

    def test_test_runner_environment_points_only_to_the_isolated_checkout(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            sandbox = Path(temporary)
            with patch.dict(os.environ, {"PYTHONPATH": str(PROJECT_ROOT)}):
                environment = capability_broker._isolated_test_environment(sandbox)

        self.assertEqual(environment["PYTHONPATH"], str(sandbox.resolve()))
        self.assertNotEqual(environment["PYTHONPATH"], str(PROJECT_ROOT.resolve()))

    def test_sandbox_outputs_settle_before_verification_starts(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            sandbox = Path(temporary)
            candidate = sandbox / "src" / "agent" / "file_bridge.py"
            candidate.parent.mkdir(parents=True)
            writer = threading.Timer(0.18, lambda: candidate.write_text("ready", encoding="utf-8"))
            started = time.monotonic()
            writer.start()
            try:
                capability_broker._wait_for_stable_sandbox_outputs(
                    sandbox, ["src/agent/file_bridge.py"],
                    required_paths=["src/agent/file_bridge.py"], quiet_s=0.1, timeout_s=2.0)
            finally:
                writer.join(timeout=1)

            self.assertTrue(candidate.is_file())
            self.assertEqual(candidate.read_text(encoding="utf-8"), "ready")
            self.assertGreaterEqual(time.monotonic() - started, 0.24)


if __name__ == "__main__":
    unittest.main()
