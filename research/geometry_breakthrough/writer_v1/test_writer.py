from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from .writer import DEFAULT_SOURCE, WRITER_ROOT, read_mp0, rebuild_mp0, run_experiment
from .verify_mp0 import verify_mp0


class FullMP0WriterTests(unittest.TestCase):
    def test_noop_full_container_is_byte_identical(self) -> None:
        source_bytes = DEFAULT_SOURCE.read_bytes()
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        image = read_mp0(DEFAULT_SOURCE)
        self.assertEqual(image.block_count, 2956)
        self.assertEqual(rebuild_mp0(image, {}), source_bytes)
        self.assertEqual(hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest(), source_sha)

    def test_full_file_edit_independent_readback(self) -> None:
        source_sha = hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="test-full-mp0-", dir=WRITER_ROOT) as folder:
            output = Path(folder) / "edited.MP0"
            report = run_experiment(DEFAULT_SOURCE, output, block=886, edge=1,
                                    point_index=1, dx=5, dy=0)
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(output.is_file())
            self.assertNotEqual(output.read_bytes(), DEFAULT_SOURCE.read_bytes())
            independent = verify_mp0(DEFAULT_SOURCE, output, block=886, edge=1,
                                     point_index=1, dx=5, dy=0)
            self.assertEqual(independent["status"], "PASS")
            self.assertEqual(independent["all_streams_decompressed"], 2956)
            self.assertEqual(independent["independently_read_edges"], 1_090_323)
            self.assertEqual(independent["unchanged_blocks_byte_identical_after_independent_inflate"], 2955)
            self.assertEqual(independent["changed_decoded_blocks"], [886])
            self.assertEqual(independent["target"]["after_point"], [2226181, 4865541])
            self.assertEqual(independent["target"]["length_raw_feet"], 601)
        self.assertEqual(hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest(), source_sha)


if __name__ == "__main__":
    unittest.main(verbosity=2)
