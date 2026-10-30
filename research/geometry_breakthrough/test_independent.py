import unittest
from decoder import blocks,ROOT,decode_mp0_polylines,decode_runs
from independent_verify import independent_blocks
class IndependentPipelineTests(unittest.TestCase):
 def test_whole_original_independent_readback(self):
  total=0
  for left,right in zip(blocks((ROOT/'EUZ.MP0').read_bytes(),True),independent_blocks(),strict=True):
   block,box,off,size,raw=left;i,nodes,other,lines=right;self.assertEqual(i,block)
   actual=decode_mp0_polylines(raw);self.assertEqual(len(actual),len(lines))
   for a,b in zip(actual,lines):
    self.assertEqual(a['coordinates_integer'],b['points']);self.assertEqual(a['length_field'],b['length_raw']);total+=1
  self.assertEqual(total,1090323)
 def test_secondary_signed_dx(self):
  import struct
  d=struct.pack('<Hii hh',1,100,100,-5,9)
  self.assertEqual(decode_runs(d,0,len(d),2,signed_x=True)[0],[(100,100),(95,109)])
if __name__=='__main__':unittest.main()
