import tempfile
import unittest
from pathlib import Path
from db_lab.analysis.entropy import profile
from db_lab.compression.comp01_lab import transforms, score
from db_lab.core.db_reader import DBReader

class LaboratoryTests(unittest.TestCase):
    def test_entropy_profile(self):
        self.assertEqual(profile(b"" )["entropy"],0.0)
        self.assertEqual(profile(b"\x00\x00")["zero_ratio"],1.0)
        self.assertEqual(profile(bytes((0,1)))["entropy"],1.0)

    def test_candidate_transform_funnel_is_bounded(self):
        candidates=list(transforms(b"abc"))
        self.assertEqual(len(candidates),263)
        self.assertEqual(candidates[0],("identity",b"abc"))
        value,features=score(b"\x00\x01",{"entropy":1.0,"zero_ratio":0.5,"unique_bytes":2})
        self.assertGreaterEqual(value,0)
        self.assertEqual(features["length"],2)

    def test_reader_opens_input_read_only_and_indexes_valid_record(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"DB_0"
            data=bytearray(1024)
            data[512:520]=bytes([0,0,1,1,0,0x0A,0,1])
            # This exact EOF record has one sector physical span and one logical unit.
            p.write_bytes(data)
            with DBReader(p) as db:
                self.assertEqual(len(db.blocks),1)
                self.assertEqual(db.blocks[0].sector,1)
                self.assertEqual(db.blocks[0].block_type,0x0A)
                self.assertEqual(db.raw(db.blocks[0])[0:4],b"\x00\x00\x01\x01")
            self.assertEqual(p.read_bytes(),bytes(data))

if __name__=="__main__": unittest.main()
