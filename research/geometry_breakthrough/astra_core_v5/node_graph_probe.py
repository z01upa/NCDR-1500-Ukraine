"""Frozen-rule Section4 continuation probe. Original sources are read-only.
Reuses established transport/coordinate readers only; adjacency is implemented here.
"""
from pathlib import Path
import sys,json,struct,hashlib
from collections import Counter,defaultdict
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE.parent/'topology_v3'))
from node_link_validator import _read_container,_sections,_coords,SOURCE

def decode_node_links(raw):
 """Return exact physical head IDs and links; continuation IDs stay distinct."""
 s,c=_sections(raw)
 if s[5]-s[4]!=10*c[4]:raise ValueError('node extent')
 heads={};owners={};n=0
 while n<c[4]:
  at=s[4]+10*n;r=raw[at:at+10];degree=r[0]&15
  if not 1<=degree<=7:raise ValueError(f'unsupported head degree at {n}: {degree}')
  if degree<=4:refs=list(struct.unpack_from('<'+'H'*degree,r,2));step=1
  else:
   if n+1>=c[4]:raise ValueError('missing continuation')
   refs=list(struct.unpack_from('<3H',r,4))+list(struct.unpack_from('<'+'H'*(degree-3),raw,at+10));owners[n+1]=n;step=2
  if any(e>=c[5] for e in refs):raise ValueError('edge ref outside table')
  heads[n]={'degree':degree,'edges':refs,'header_hex':r[:4 if degree>4 else 2].hex(),'record_hex':r.hex(),'continuation':n+1 if step==2 else None}
  n+=step
 return heads,owners

def incidence(raw):
 s,c=_sections(raw);out=[[] for _ in range(c[4])];secondary=[]
 for e in range(c[5]):
  at=s[5]+14*e;flags=int.from_bytes(raw[at:at+2],'little')
  for off,bit in [(6,4096),(8,8192)]:
   index=int.from_bytes(raw[at+off:at+off+2],'little')
   if flags&bit:
    if index>=c[2]:raise ValueError('secondary index')
    secondary.append((e,index))
   else:
    if index>=c[4]:raise ValueError('primary index')
    out[index].append(e)
 return out,secondary

def coordinates(raw):
 s,c=_sections(raw)
 return (_coords(raw,s[0],s[1],c[0],False),_coords(raw,s[2],s[3],c[2],True))

def run():
 data,blocks=_read_container(SOURCE);freeze=(HERE/'evidence/pass_a_frozen_rule.json').read_bytes();dev=set(json.loads(freeze)['discovery_blocks']);dev_coords=set()
 for i in dev:
  a,b=coordinates(blocks[i]);dev_coords.update(a);dev_coords.update(b)
 cohorts={};metrics=defaultdict(Counter);degree_counts=defaultdict(Counter);failures=[];continuations=[];examples={};opaque=Counter();copy_sig=defaultdict(set)
 prior=json.loads((HERE.parent/'topology_v3/evidence/node_link_validation.json').read_text())
 for i,b in enumerate(blocks):
  a,z=coordinates(b);cohort='discovery' if i in dev else ('quarantine' if any(x in dev_coords for x in a+z) else 'holdout');cohorts[i]=cohort
  s,c=_sections(b);inc,sec=incidence(b);heads,owners=decode_node_links(b);t=metrics[cohort];t['blocks']+=1;t['physical_records']+=c[4];t['heads']+=len(heads);t['continuations']+=len(owners);t['secondary_endpoints']+=len(sec)
  for n,h in heads.items():
   deg=h['degree'];degree_counts[cohort][deg]+=1
   if Counter(h['edges'])!=Counter(inc[n]):failures.append({'block':i,'node':n,'refs':h['edges'],'incidence':inc[n]});t['identity_failures']+=1
   else:t['exact_head_multisets']+=1
   if deg>4:
    r=b[s[4]+10*n:s[4]+10*n+20];w=int.from_bytes(r[2:4],'little');opaque['heads']+=1;opaque['plus2_outside_node_index']+=w>=c[4];opaque['plus2_outside_edge_index']+=w>=c[5];opaque['plus2_not_next_node']+=w!=n+1
    continuations.append({'block':i,'cohort':cohort,'head_node':n,'continuation_record':n+1,'degree':deg,'raw20_hex':r.hex(),'plus2_u16':w,'decoded_edge_ids':h['edges'],'incidence_edge_ids':inc[n],'same_coordinate':a[n]==a[n+1]})
   key=f'degree{deg}'
   if cohort=='holdout' and key not in examples:
    examples[key]={'block':i,'node':n,'cohort':cohort,**h,'incidence':inc[n]};(HERE/'evidence'/f'control_block_{i}.bin').write_bytes(b)
   if cohort=='holdout' and deg==3 and int.from_bytes(b[s[4]+10*n+8:s[4]+10*n+10],'little') and 'degree3_nonzero_plus8' not in examples:examples['degree3_nonzero_plus8']={'block':i,'node':n,**h}
  for n,owner in owners.items():
   r=b[s[4]+10*n:s[4]+10*(n+1)];low=r[0]&15;t['continuation_apparent_low_'+str(low)]+=1;t['continuation_has_no_primary_incidence']+=not inc[n];t['continuation_same_coordinate_as_head']+=a[n]==a[owner]
   if inc[n]:failures.append({'block':i,'continuation':n,'unexpected_incidence':inc[n]})
  # Leakage check signatures include endpoint pairs AND length; coordinate equality only excludes data, never merges graph identities.
  for e,si in sec:
   f,at,k,u,v,length=struct.unpack_from('<5HI',b,s[5]+14*e);p=z[u] if f&4096 else a[u];q=z[v] if f&8192 else a[v]
   copy_sig[(tuple(sorted((p,q))),length)].add(cohort)
 old=prior['low_degree_identity_adjacency'];old_rows=old.get('all_mismatches',old.get('mismatch_records',[]))
 # Cohort-wide exact coverage, without relying on undocumented JSON key names.
 coverage={'previous_511':sum(v.get('continuation_apparent_low_'+str(d),0) for v in metrics.values() for d in range(1,5)), 'previous_1325':sum(v.get('continuation_apparent_low_'+str(d),0) for v in metrics.values() for d in range(5,16)), 'apparent_degree0_continuations':sum(v.get('continuation_apparent_low_0',0) for v in metrics.values())}
 report={'source':str(SOURCE),'sha256_before':hashlib.sha256(data).hexdigest(),'sha256_after':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'frozen_rule_sha256':hashlib.sha256(freeze).hexdigest(),'cohort_blocks':{k:[i for i,v in cohorts.items() if v==k] for k in metrics},'metrics':{k:dict(v) for k,v in metrics.items()},'head_degree_counts':{k:dict(v) for k,v in degree_counts.items()},'failures':failures,'continuation_coverage':coverage,'discovery_holdout_shared_border_signatures':sum('discovery' in v and 'holdout' in v for v in copy_sig.values()),'plus2_pointer_rejections':dict(opaque),'examples':examples,'claim':'Section4 head/continuation layout only; routing masks and inactive bytes unresolved'}
 (HERE/'evidence/node_graph_validation.json').write_text(json.dumps(report,indent=2));(HERE/'evidence/continuations.json').write_text(json.dumps(continuations,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ['cohort_blocks','examples']},indent=2))
 return report
if __name__=='__main__':run()
