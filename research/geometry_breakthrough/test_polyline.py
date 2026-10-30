import unittest,struct,math
from pathlib import Path
from decoder import decode_mp0_polylines
HERE=Path(__file__).parent
class PolylineTests(unittest.TestCase):
 def test_three_blocks_primary_lengths(self):
  for i in range(3):
   d=(HERE/'evidence'/f'MP0_{i}.bin').read_bytes();lines=decode_mp0_polylines(d)
   selected=[r for r in lines if not r['flags']&0x3000][:3]
   self.assertEqual(len(selected),3)
   for row in selected:
    self.assertFalse(row['flags']&0x3000)
    pts=row['coordinates_integer'];dist=0
    for (x,y),(xx,yy) in zip(pts,pts[1:]):
     p1,p2=math.radians(y/1e5),math.radians(yy/1e5);dl=math.radians((xx-x)/1e5);dp=p2-p1
     h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
     dist+=12742017.6*math.asin(min(1,math.sqrt(h)))
    expected=row['length_field']*.3048
    self.assertLess(abs(dist-expected),max(5,expected*.02))
 def test_shape_table_corruption(self):
  d=bytearray((HERE/'evidence/MP0_0.bin').read_bytes());start=int.from_bytes(d[40:42],'little');d[start:start+2]=b'\0\0'
  with self.assertRaises(ValueError):decode_mp0_polylines(d)
 def test_shape_count_corruption(self):
  d=bytearray((HERE/'evidence/MP0_0.bin').read_bytes());start=int.from_bytes(d[20:22],'little');d[start+1]^=128
  with self.assertRaises(ValueError):decode_mp0_polylines(d)
if __name__=='__main__':unittest.main()

