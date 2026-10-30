from __future__ import annotations

import unittest
from unittest import mock

from src.agent import coordinator, coordinator_runtime


class CoordinatorAdapterTests(unittest.TestCase):
    def test_windows_subprocesses_do_not_create_console_windows(self) -> None:
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(coordinator.sys, "platform", "win32"), \
             mock.patch.object(coordinator.subprocess, "run", return_value=completed) as run:
            result = coordinator._run(["probe.exe"], timeout=7)

        self.assertEqual(result["returncode"], 0)
        self.assertEqual(run.call_args.kwargs["timeout"], 7)
        self.assertEqual(run.call_args.kwargs["creationflags"], coordinator.subprocess.CREATE_NO_WINDOW)

    def test_public_run_reports_next_action_from_persisted_queue_summary(self) -> None:
        runtime_result = {
            "completed_this_run": [],
            "status": {"task_counts": {"PENDING": 0, "LEASED": 0, "BLOCKED": 3}},
            "next_action": "generic runtime guidance",
        }
        with mock.patch.object(coordinator_runtime, "run", return_value=runtime_result) as adaptive_run:
            result = coordinator.run(max_tasks=2, owner="test-owner", max_seconds=45)

        adaptive_run.assert_called_once_with(max_tasks=2, owner="test-owner", max_seconds=45)
        self.assertIn("documented blocker", result["next_action"])

    def test_next_action_waits_for_a_leased_task_before_recommending_requeue(self) -> None:
        result = coordinator._next_action({"task_counts": {"LEASED": 1, "BLOCKED": 4}})
        self.assertIn("active bounded task", result)
        self.assertNotIn("requeue", result)


if __name__ == "__main__":
    unittest.main()
