from __future__ import annotations

import sys
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.benchmark_runner import score_task


class BenchmarkScoringTests(unittest.TestCase):
    def test_mp0_scoring_accepts_the_observed_0x30_offset(self) -> None:
        code = """def parse_mp0_dataset_code(data):
    if len(data) < 64:
        raise ValueError('truncated')
    return data[0x30:0x40].split(b'\\0', 1)[0].decode('ascii')
"""
        passed, _ = score_task({"kind": "code_mp0"}, {"code": code})
        self.assertTrue(passed)

    def test_mp0_scoring_rejects_the_stale_0x31_offset(self) -> None:
        code = """def parse_mp0_dataset_code(data):
    if len(data) < 65:
        raise ValueError('truncated')
    return data[0x31:0x41].split(b'\\0', 1)[0].decode('ascii')
"""
        passed, _ = score_task({"kind": "code_mp0"}, {"code": code})
        self.assertFalse(passed)


if __name__ == "__main__":
    unittest.main()
