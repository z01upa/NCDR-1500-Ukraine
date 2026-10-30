import unittest,json,copy,struct
from pathlib import Path
from encoder import encode_shapes
from decoder import decode_mp0_polylines
from independent_verify import independent_blocks
HERE=Path(__file__).parent
class EncoderTests(unittest.TestCase):
 def test_confirmed_block_noop(self):
  b=(HERE/'evidence/MP0_886.bin').read_bytes();self.assertEqual(encode_shapes(b,decode_mp0_polylines(b)),b)
 def test_independent_modified_envelope(self):
  row=list(independent_blocks(HERE/'evidence/experimental_one_block.MP0'))[0][3][1]
  self.assertEqual(row['points'][1],(2226181,4865541))
 def test_reject_delta_overflow(self):
  b=(HERE/'evidence/MP0_886.bin').read_bytes();lines=decode_mp0_polylines(b);x,y=lines[1]['coordinates_integer'][1];lines[1]['coordinates_integer'][1]=(x+100000,y)
  with self.assertRaises(ValueError):encode_shapes(b,lines)
 def test_local_reference_match(self):
  report=json.loads((HERE/'evidence/local_comparison.json').read_text());self.assertEqual(len(report['all_candidate_metrics']),42);match=report['selected'][0]
  self.assertEqual((match['block'],match['edge']),(886,1));self.assertLess(match['max_residual_m'],2.01);self.assertGreater(match['shift500_median_m'],100)
if __name__=='__main__':unittest.main()
