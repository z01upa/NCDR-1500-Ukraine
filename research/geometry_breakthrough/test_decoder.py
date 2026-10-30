"""Independent fixture and corruption tests; no production Reader imports."""
import unittest,struct,json,hashlib
from pathlib import Path
from decoder import decode_runs,blocks,ROOT
HERE=Path(__file__).parent
class DecoderTests(unittest.TestCase):
 def test_fixture_independent_coordinates(self):
  for f in (HERE/'evidence').glob('*.bin'):
   d=f.read_bytes()
   for section in [0,2]:
    start,n=struct.unpack_from('<HH',d,section*4);end=struct.unpack_from('<H',d,section*4+4)[0]
    actual,runs=decode_runs(d,start,end,n,signed_x=(section==2));expected=[];cursor=start
    while cursor<end:
     remaining=int.from_bytes(d[cursor:cursor+2],'little');x=int.from_bytes(d[cursor+2:cursor+6],'little',signed=True);y=int.from_bytes(d[cursor+6:cursor+10],'little',signed=True);cursor+=10;expected.append((x,y))
     for k in range(remaining):
      x+=int.from_bytes(d[cursor:cursor+2],'little',signed=(section==2));y+=int.from_bytes(d[cursor+2:cursor+4],'little',signed=True);cursor+=4;expected.append((x,y))
    self.assertEqual(cursor,end);self.assertEqual(len(expected),n);self.assertEqual(actual,expected)
 def test_reject_count(self):
  d=(HERE/'evidence/MP0_0.bin').read_bytes()
  with self.assertRaises(ValueError):decode_runs(d,46,564,127)
 def test_reject_truncated_run(self):
  with self.assertRaises(ValueError):decode_runs(b'\0'*9,0,9,1)
 def test_unsigned_x_signed_y(self):
  d=struct.pack('<HiiHh',1,-100,200,50000,-300)
  self.assertEqual(decode_runs(d,0,len(d),2)[0],[(-100,200),(49900,-100)])
 def test_all_source_hashes_and_extents(self):
  audit=json.loads((HERE/'evidence/coordinate_audit.json').read_text())
  for ext,entry in audit.items():
   data=Path(entry['source']).read_bytes();self.assertEqual(hashlib.sha256(data).hexdigest(),entry['source_sha256'])
   ranges=[]
   for row,decoded in zip(entry['rows'],blocks(data,ext=='MP0'),strict=True):
    i,box,p,c,raw=decoded;self.assertEqual(hashlib.sha256(raw).hexdigest(),row['sha256']);ranges.append((p,p+c))
   ranges.sort();self.assertEqual(ranges[0][0],114+28*len(ranges));self.assertEqual(ranges[-1][1],len(data))
   self.assertTrue(all(a[1]==b[0] for a,b in zip(ranges,ranges[1:])))
if __name__=='__main__':unittest.main(verbosity=2)
