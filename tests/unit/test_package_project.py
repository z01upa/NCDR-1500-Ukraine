from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import package_project


class PackageProjectTests(unittest.TestCase):
    def test_runtime_lock_files_are_not_included_in_source_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            root = Path(directory) / "project"
            lock = root / "work" / "worker.lock"
            lock.parent.mkdir(parents=True)
            lock.write_text("", encoding="utf-8")
            regular = root / "reports" / "result.json"
            regular.parent.mkdir(parents=True)
            regular.write_text("{}", encoding="utf-8")
            with patch.object(package_project, "PROJECT_ROOT", root):
                self.assertFalse(package_project.should_include(lock))
                self.assertTrue(package_project.should_include(regular))


if __name__ == "__main__":
    unittest.main()
