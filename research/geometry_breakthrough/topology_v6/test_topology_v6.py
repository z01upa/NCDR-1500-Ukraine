from pathlib import Path
import unittest,json,gzip,struct,hashlib
from dataclasses import replace
from collections import Counter
from topology_decoder import *
HERE=Path(__file__).parent;OUT=HERE/'evidence'
class ConsolidationTests(unittest.TestCase):
 def fixture(self,degree):
  b=(OUT/f'fixture_degree{degree}.bin').read_bytes();s,c=layout(b);part=b[s[4]:s[5]];return b,s,c,part,decode_section4(part,c[5])
 def test_degree1_through7_noop(self):
  for d in range(1,8):
   b,s,c,part,nodes=self.fixture(d);self.assertEqual(encode_section4(nodes),part);self.assertTrue(any(n.degree==d for n in nodes))
 def test_inmemory_active_word_permutation_preserves_abstract_adjacency(self):
  b,s,c,part,nodes=self.fixture(5);index=next(i for i,n in enumerate(nodes) if n.degree==5);n=nodes[index];changed=nodes[:];changed[index]=replace(n,edges=(n.edges[1],n.edges[0],*n.edges[2:]));result=encode_section4(changed)
  differences=[i for i,(x,y) in enumerate(zip(part,result)) if x!=y]
  self.assertTrue(differences);self.assertTrue(all(n.physical_id*10+4<=i<n.physical_id*10+8 for i in differences))
  recovered=decode_section4(result,c[5]);self.assertEqual(Counter(recovered[index].edges),Counter(n.edges))
  self.assertEqual(recovered[index].opaque_prefix,n.opaque_prefix);self.assertEqual(recovered[index].opaque_suffix,n.opaque_suffix)
  recovered[index]=replace(recovered[index],edges=n.edges);self.assertEqual(encode_section4(recovered),part)
  # Abstract unordered adjacency only; no assertion about turn masks/runtime semantics.
 def test_wrong_inmemory_edge_detected_by_endpoint_oracle(self):
  b,s,c,part,nodes=self.fixture(6);i=next(i for i,n in enumerate(nodes) if n.degree==6);n=nodes[i];wrong=next(e for e in range(c[5]) if e not in n.edges);edited=nodes[:];edited[i]=replace(n,edges=(*n.edges[:-1],wrong));rec=decode_section4(encode_section4(edited),c[5]);oracle=Counter(e for e,side,t,v in endpoint_oracle(b) if t=='primary' and v==n.physical_id)
  self.assertNotEqual(Counter(rec[i].edges),oracle)
 def test_degree_changes_refuse_opaque_overwrite(self):
  for degree in [3,4]:
   b,s,c,part,nodes=self.fixture(degree);n=next(n for n in nodes if n.degree==degree);self.assertFalse(transition_plan(n,c[5])['allowed'])
   i=nodes.index(n);mutated=nodes[:];mutated[i]=replace(n,degree=degree+1,edges=n.edges+(c[5],))
   with self.assertRaises(ValueError):encode_section4(mutated)
   self.assertEqual(encode_section4(nodes),part)
 def test_zero_head_is_not_invented(self):
  with self.assertRaises(ValueError):decode_section4(b'\0'*10,10)
 def test_missing_continuation_rejected(self):
  with self.assertRaises(ValueError):decode_section4(b'\x05\0'+b'\0'*8,10)
 def test_complete_export_has_exact_counts_and_unique_ids(self):
  count=0;lastblock=-1;expected_ordinal=0;nextphysical=0;degree=Counter();high=0
  with gzip.open(OUT/'logical_adjacency.jsonl.gz','rt',encoding='utf8') as f:
   for line in f:
    r=json.loads(line)
    if r['block']!=lastblock:
     self.assertEqual(r['block'],lastblock+1);lastblock=r['block'];expected_ordinal=0;nextphysical=0
    self.assertEqual(r['logical_ordinal'],expected_ordinal);self.assertEqual(r['physical_node_id'],nextphysical);self.assertEqual(len(r['edge_ids']),r['degree']);self.assertEqual(len(set(r['edge_ids'])),r['degree'])
    expected_ordinal+=1;nextphysical+=1+(r['degree']>4);count+=1;degree[r['degree']]+=1;high+=r['degree']>4
  self.assertEqual((count,high,lastblock),(954116,1955,2955))
 def test_full_evidence_acceptance_and_source_hash(self):
  r=json.loads((OUT/'acceptance.json').read_text());self.assertEqual(r['problems'],[]);self.assertEqual(r['counts']['noop_blocks'],2956);self.assertEqual(r['adjacency_membership_sha256'],r['section5_primary_membership_sha256']);self.assertTrue(r['old511_exact_identity_set_equal']);self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(),EXPECTED)
if __name__=='__main__':unittest.main(verbosity=2)
