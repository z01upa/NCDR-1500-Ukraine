from __future__ import annotations

import unittest

from src.agent.capability_broker import _normalize_unified_diff


DIFF = """diff --git a/src/sample.py b/src/sample.py
index 1111111..2222222 100644
--- a/src/sample.py
+++ b/src/sample.py
@@ -1 +1 @@
-value = 1
+value = 2
"""


class CapabilityPatchFormatTests(unittest.TestCase):
    def test_accepts_git_diff_with_surrounding_whitespace(self) -> None:
        self.assertEqual(_normalize_unified_diff("\n  " + DIFF + "  \n"), DIFF)

    def test_accepts_fenced_diff_after_short_model_preamble(self) -> None:
        response = "Patch follows:\n```diff\n" + DIFF + "```"
        self.assertEqual(_normalize_unified_diff(response), DIFF)

    def test_accepts_standard_unified_diff_without_git_header(self) -> None:
        response = "--- a/src/sample.py\n+++ b/src/sample.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
        self.assertEqual(_normalize_unified_diff(response), response.rstrip() + "\n")

    def test_rejects_empty_prose_and_unbounded_output(self) -> None:
        for response in ("", "No patch was produced.", "x" * 500_001):
            with self.subTest(response_length=len(response)):
                with self.assertRaises(ValueError):
                    _normalize_unified_diff(response)


if __name__ == "__main__":
    unittest.main()
