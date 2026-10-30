from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.file_bridge import FileTaskBridge


class FileTaskBridgeTests(unittest.TestCase):
    def test_task_and_result_round_trip_through_atomic_files_and_sqlite(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            bridge = FileTaskBridge(root / "bridge", root / "bridge.sqlite")
            task = {"id": "A09-001", "schema_version": 1,
                    "objective": "verify a bounded NCDR task", "payload": {"region": "UA"}}
            result = {"task_id": "A09-001", "schema_version": 1,
                      "status": "PASS", "payload": {"verified": True}}

            self.assertTrue(bridge.enqueue_task(task))
            self.assertEqual(bridge.read_task("A09-001"), task)
            self.assertFalse(bridge.enqueue_task(task))
            self.assertTrue(bridge.publish_result(result))
            self.assertEqual(bridge.read_result("A09-001"), result)
            self.assertFalse(bridge.publish_result(result))

            self.assertTrue((root / "bridge" / "TASKS" / "A09-001.json").is_file())
            self.assertTrue((root / "bridge" / "RESULTS" / "A09-001.json").is_file())
            self.assertEqual(list((root / "bridge").rglob("*.tmp")), [])
            self.assertEqual(bridge.outbox_count(), 1)
            self.assertEqual(bridge.inbox_count(), 1)

    def test_schema_rejects_missing_fields_and_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            bridge = FileTaskBridge(root / "bridge", root / "bridge.sqlite")
            with self.assertRaises(ValueError):
                bridge.enqueue_task({"id": "BROKEN", "schema_version": 1})
            with self.assertRaises(ValueError):
                bridge.enqueue_task({"id": "../escape", "schema_version": 1,
                                     "objective": "unsafe id", "payload": {}})
            with self.assertRaises(ValueError):
                bridge.publish_result({"task_id": "A09-002", "schema_version": 1,
                                       "status": "UNKNOWN", "payload": {}})
            self.assertEqual(bridge.outbox_count(), 0)
            self.assertEqual(bridge.inbox_count(), 0)

    def test_conflicting_duplicate_is_rejected_without_overwriting_first_record(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            bridge = FileTaskBridge(root / "bridge", root / "bridge.sqlite")
            task = {"id": "A09-003", "schema_version": 1,
                    "objective": "first payload", "payload": {"value": 1}}
            bridge.enqueue_task(task)
            conflict = {**task, "payload": {"value": 2}}
            with self.assertRaises(ValueError):
                bridge.enqueue_task(conflict)
            self.assertEqual(bridge.read_task("A09-003"), task)


if __name__ == "__main__":
    unittest.main()
