"""New tests for continuation mechanism, not legacy geometry/writer regressions."""
import unittest,json,struct
from collections import Counter
from node_graph_probe import HERE,decode_node_links,incidence,_sections,_read_container,SOURCE
class ContinuationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.report=json.loads((HERE/'evidence/node_graph_validation.json').read_text());cls.data,cls.blocks=_read_container(SOURCE)
 def test_all_frozen_control_identity(self):
  # Independent oracle: section5 endpoint identity; decode all held-out node chains.
  for bi in self.report['cohort_blocks']['holdout']:
   b=self.blocks[bi];heads,owners=decode_node_links(b);expected,sec=incidence(b)
   self.assertEqual(set(heads)|set(owners),set(range(len(expected))))
   for n,h in heads.items():self.assertEqual(Counter(h['edges']),Counter(expected[n]))
   for n in owners:self.assertEqual(expected[n],[])
 def test_exact_old_511_identities(self):
  old=json.loads((HERE.parent/'topology_v3/evidence/node_link_validation.json').read_text())['low_degree_identity_adjacency']['all_mismatch_records']
  self.assertEqual(len(old),511)
  for row in old:
   heads,owners=decode_node_links(self.blocks[row['block']]);self.assertIn(row['node'],owners);self.assertNotIn(row['node'],heads)
 def test_degrees_2_through_7(self):
  for degree in range(2,8):
   ex=self.report['examples'][f'degree{degree}'];heads,owners=decode_node_links(self.blocks[ex['block']]);self.assertEqual(heads[ex['node']]['degree'],degree);self.assertEqual(sorted(heads[ex['node']]['edges']),sorted(ex['incidence']))
 def test_nonzero_plus8_not_adjacency_for_degree3(self):
  ex=self.report['examples']['degree3_nonzero_plus8'];r=bytes.fromhex(ex['record_hex']);self.assertNotEqual(int.from_bytes(r[8:10],'little'),0)
  self.assertEqual(len(ex['edges']),3)
 def test_continuation_mutation_detected(self):
  ex=self.report['examples']['degree5'];b=bytearray(self.blocks[ex['block']]);s,c=_sections(b);at=s[4]+10*(ex['node']+1)
  # Different but still in-range edge: must break exact endpoint identity.
  expected,_=incidence(b);replacement=next(i for i in range(c[5]) if i not in expected[ex['node']]);struct.pack_into('<H',b,at,replacement)
  heads,_=decode_node_links(b);self.assertNotEqual(Counter(heads[ex['node']]['edges']),Counter(expected[ex['node']]))
 def test_plus2_not_needed_for_adjacency_only(self):
  ex=self.report['examples']['degree7'];b=bytearray(self.blocks[ex['block']]);s,c=_sections(b);before,_=decode_node_links(b);at=s[4]+10*ex['node']+2;b[at:at+2]=b'\x00\x00';after,_=decode_node_links(b)
  self.assertEqual(before[ex['node']]['edges'],after[ex['node']]['edges'])
  # This proves the adjacency algorithm ignores it, NOT that firmware ignores it.
 def test_source_unchanged(self):
  import hashlib
  self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(),self.report['sha256_before'])
 def test_no_split_border_copy_leak(self):
  self.assertEqual(self.report['discovery_holdout_shared_border_signatures'],0)
  self.assertEqual(len(self.report['cohort_blocks']['holdout']),2876)
if __name__=='__main__':unittest.main(verbosity=2)
