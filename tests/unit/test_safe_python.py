from __future__ import annotations

import sys
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.safe_python import ScriptRejected, run_research_script


class SafePythonTests(unittest.TestCase):
    def test_runs_data_only_calculation_in_child(self) -> None:
        result = run_research_script('total = sum(data["values"])\nprint(total)', {"values": [2, 3, 5]})
        self.assertEqual(result["result"]["total"], 10)
        self.assertEqual(result["stdout"], "10\n")
        self.assertGreater(result["memory_limit_bytes"], 0)

    def test_isolated_windows_child_serializes_ukrainian_utf8(self) -> None:
        result = run_research_script('label = "Кривий Ріг"\nprint(label)')
        self.assertEqual(result["result"]["label"], "Кривий Ріг")
        self.assertEqual(result["stdout"], "Кривий Ріг\n")

    def test_import_and_file_access_are_rejected(self) -> None:
        for source in ("import os", "open('x')", "x = data.__class__", "exec('print(1)')"):
            with self.subTest(source=source), self.assertRaises(ScriptRejected):
                run_research_script(source)

    def test_infinite_loop_and_large_repeat_are_rejected(self) -> None:
        with self.assertRaises(ScriptRejected):
            run_research_script("while True: pass")
        with self.assertRaises(ScriptRejected):
            run_research_script("x = [0] * 1000000000")

    def test_constant_loop_is_bounded_and_runs(self) -> None:
        result = run_research_script("total = 0\nfor i in range(4):\n total += i\n")
        self.assertEqual(result["result"]["total"], 6)

    def test_model_script_can_compare_three_bounded_prefixes(self) -> None:
        code = ("common_prefix = 0\nfor i in range(4):\n"
                " if data['prefixes'][0][i] == data['prefixes'][1][i] and data['prefixes'][1][i] == data['prefixes'][2][i]:\n"
                "  common_prefix += 1\n else:\n  break\n")
        result = run_research_script(code, {"prefixes": [[1, 2, 3, 4], [1, 2, 3, 5], [1, 2, 3, 4]]})
        self.assertEqual(result["result"]["common_prefix"], 3)


if __name__ == "__main__":
    unittest.main()
