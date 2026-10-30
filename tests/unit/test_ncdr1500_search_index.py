import importlib.util
from pathlib import Path
import struct
import unittest

SOURCE=Path(__file__).with_name('ncdr1500_search_index.py')
if not SOURCE.is_file():
    SOURCE=Path(__file__).resolve().parents[2]/'src'/'readers'/'ncdr1500_search_index.py'
SPEC=importlib.util.spec_from_file_location('ct_index',SOURCE)
MOD=importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name]=MOD
SPEC.loader.exec_module(MOD)

def make_sample():
    header=bytearray(94)
    header[:7]=b'SIEMENS'
    struct.pack_into('<HI',header,84,20,3)
    # root, two leaf nodes => covers two synthetic CL rows.
    return bytes(header) + struct.pack('<IHII',1234,2*256,0,2) + struct.pack('<IHII',65,0,0,1) + struct.pack('<IHII',66,0,1,1)

class CTReaderTests(unittest.TestCase):
    def test_small_valid_tree(self):
        result=MOD.analyze_bytes(make_sample(),2)
        self.assertEqual(result['leaf_records'],2)
        self.assertEqual(result['root_children'],2)
    def test_bad_child_count_is_rejected(self):
        data=bytearray(make_sample()); struct.pack_into('<H',data,94+4,256)
        with self.assertRaises(ValueError): MOD.analyze_bytes(bytes(data),2)
    def test_bad_interval_is_rejected(self):
        data=bytearray(make_sample()); struct.pack_into('<I',data,94+14+6,2)
        with self.assertRaises(ValueError): MOD.analyze_bytes(bytes(data),2)
    def test_wrong_type_is_rejected(self):
        data=bytearray(make_sample()); struct.pack_into('<H',data,84,3)
        with self.assertRaises(ValueError): MOD.analyze_bytes(bytes(data),2)

if __name__=='__main__': unittest.main()
