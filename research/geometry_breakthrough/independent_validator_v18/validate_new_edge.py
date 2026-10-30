#!/usr/bin/env python3
"""Comparative MP0 new-edge validator; read-only, stdlib, no Writer import.
Contract: existing block/node/edge IDs retained; additions append. Reindexing
requires a separate proven identity map and is not accepted by this contract.
Exit 0 PASS (local comparative checks), 1 FAIL, 2 UNKNOWN. Never hardware approval.
"""
import argparse,collections,hashlib,importlib.util,json,struct,sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent

def sha(b):return hashlib.sha256(b).hexdigest()
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

def dependencies(project=None):
 roots=([Path(project)] if project else [])+[HERE/'dependencies',HERE.parents[2]/'NCDR_ASTRA_TRANSFER/project',HERE.parents[2]]
 for root in roots:
  g=root/'research/geometry_breakthrough'
  if (g/'topology_v6/topology_decoder.py').is_file() and (g/'independent_verify.py').is_file():
   return load('v18_topology',g/'topology_v6/topology_decoder.py'),load('v18_reader',g/'independent_verify.py'),[g/'topology_v6/topology_decoder.py',g/'independent_verify.py']
 raise FileNotFoundError('Need existing research/geometry_breakthrough/topology_v6/topology_decoder.py and independent_verify.py; pass --reader-project PROJECT')

class Results:
 def __init__(self):self.rules={}
 def add(self,key,status,detail=None):
  r=self.rules.setdefault(key,dict(status='PASS',observations=0,failures=0,unknowns=0,examples=[]));r['observations']+=1
  if status=='FAIL':r['failures']+=1;r['status']='FAIL'
  elif status=='UNKNOWN':r['unknowns']+=1;r['status']='UNKNOWN' if r['status']!='FAIL' else 'FAIL'
  if status!='PASS' and len(r['examples'])<12:r['examples'].append(detail)
 def check(self,key,ok,detail):self.add(key,'PASS' if ok else 'FAIL',detail)

def inspect_block(t,b,bi,res):
 s,c=t.layout(b);nodes=t.decode_section4(b[s[4]:s[5]],c[5]);heads={n.physical_id:n for n in nodes};oracle=t.endpoint_oracle(b);coords=t.coordinate_tables(b)
 res.check('node_lossless_reader',t.encode_section4(nodes)==b[s[4]:s[5]],dict(block=bi))
 actual=collections.Counter((n.physical_id,e) for n in nodes for e in n.edges)
 expected=collections.Counter((idx,e) for e,side,table,idx in oracle if table=='primary')
 res.check('primary_incidence',actual==expected,dict(block=bi,missing=sum((expected-actual).values()),extra=sum((actual-expected).values())))
 res.check('no_endpoint_to_continuation',all(tab!='primary' or idx in heads for _,_,tab,idx in oracle),dict(block=bi))
 res.check('local_id_width',c[4]<=4096 and c[5]<=4096 and c[2]<=4096,dict(block=bi,counts=[c[4],c[5],c[2]]))
 records=[b[s[5]+14*i:s[5]+14*(i+1)] for i in range(c[5])]
 # SH4 0x01068AA0..0x01068B26: bit=0 means local node is A; bit=1 means B.
 for n in nodes:
  orient=n.upper_nibble>>4 if n.degree<=4 else n.byte1
  for slot,e in enumerate(n.edges):
   side=(orient>>slot)&1;row=oracle[2*e+side]
   res.check('node_orientation',row[2]=='primary' and row[3]==n.physical_id,dict(block=bi,node=n.physical_id,slot=slot,edge=e,bit=side,actual_endpoint=row[2:]))
 for k,stride in [(7,7),(8,11),(9,13)]:
  res.check('section_%d_record_extent'%k,s[k+1]-s[k]==c[k]*stride,dict(block=bi,section=k,count=c[k],extent=s[k+1]-s[k]))
 # Geometry reader uses a variable-length shape offset table, independently checked here for truncated indexes.
 tail=b[s[10]:];n=c[10]
 if len(tail)<2*(n+1):raise ValueError('short shape index')
 ix=struct.unpack_from('<'+'H'*(n+1),tail)
 res.check('shape_table',ix[0]==2*(n+1) and ix[-1]==len(tail) and all(x<=y and (y-x)%4==0 for x,y in zip(ix,ix[1:])),dict(block=bi))
 return s,c,heads,records,coords,oracle

def validate(original,candidate,reader_project=None):
 res=Results();report=dict(contract='NCDR-ASTRA-MAC-018/1',original=str(original),candidate=str(candidate),scope='Comparative offline insertion validation; NOT device compatibility',rules=res.rules,changed_blocks=[],added_edges=0,limitations=['No complete Windows CE emulation or hardware test.','Latest Lenovo transition-mask proof and insertion artifact are not bundled.'])
 try:
  t,reader,paths=dependencies(reader_project);report['dependencies']=[dict(file=str(p),sha256=sha(p.read_bytes())) for p in paths]
  a=Path(original).read_bytes();b=Path(candidate).read_bytes();report['original_sha256']=sha(a);report['candidate_sha256']=sha(b)
  na=int.from_bytes(a[86:90],'little');nb=int.from_bytes(b[86:90],'little')
  res.check('append_contract_blocks',na==nb,dict(before=na,after=nb))
  res.check('global_header_preserved',a[:114]==b[:114],{})
  if na!=nb:raise ValueError('new/deleted blocks outside append-to-existing-block contract')
  res.check('opaque_index_preserved',a[114+24*na:114+28*na]==b[114+24*nb:114+28*nb],{})
  # Exhaust both topology generators: trailing global stream coverage checks must execute.
  ga=iter(t.read_blocks(a));gb=iter(t.read_blocks(b));geometry_old=iter(reader.independent_blocks(original));geometry_new=iter(reader.independent_blocks(candidate))
  borders_old=collections.Counter();borders_new=collections.Counter()
  for bi in range(na):
   ia,old=next(ga);ib,new=next(gb);assert ia==ib==bi
   sa,ca,ha,ea,coa,oa=inspect_block(t,old,bi,res);sn,cn,hn,en,con,on=inspect_block(t,new,bi,res)
   res.check('old_bbox_preserved',a[114+24*bi:130+24*bi]==b[114+24*bi:130+24*bi],dict(block=bi))
   # IDs, rather than equal coordinates, determine existing record identity.
   res.check('no_deleted_records',cn[5]>=ca[5] and cn[4]>=ca[4] and cn[2]>=ca[2],dict(block=bi))
   report['added_edges']+=max(0,cn[5]-ca[5]);changed=old!=new
   if changed:report['changed_blocks'].append(bi)
   touched=set()
   for nid,n in ha.items():
    nn=hn.get(nid)
    res.check('old_node_identity',nn is not None,dict(block=bi,node=nid))
    if nn is None:continue
    if n.edges!=nn.edges:touched.add(nid)
    res.check('old_adjacency_members_retained',not (collections.Counter(n.edges)-collections.Counter(nn.edges)),dict(block=bi,node=nid))
    # Inactive fields are preserved wherever they remain inactive. Newly consumed opaque storage is a gate.
    op=2 if n.degree<=4 else 4;np=2 if nn.degree<=4 else 4
    oldactive=set(range(op,op+2*n.degree));newactive=set(range(np,np+2*nn.degree))
    for off in range(2,min(n.physical_span,nn.physical_span)*10):
     if off not in oldactive and off not in newactive:res.check('old_node_opaque_bytes',old[sa[4]+nid*10+off]==new[sn[4]+nid*10+off],dict(block=bi,node=nid,offset=off))
    if n.degree<=4 and nn.degree<=4:res.check('low_degree_byte1_preserved',n.byte1==nn.byte1,dict(block=bi,node=nid))
    if n.degree>4 and nn.degree>4:res.check('high_degree_upper_nibble_preserved',n.upper_nibble==nn.upper_nibble,dict(block=bi,node=nid))
    if n.degree!=nn.degree:res.add('opaque_degree_transition','UNKNOWN',dict(block=bi,node=nid,before=n.degree,after=nn.degree,reason='previously inactive storage/header dependencies require proof'))
   for e,(x,y) in enumerate(zip(ea,en)):
    res.check('old_edge_nonmask_fields',x[:4]+x[6:]==y[:4]+y[6:],dict(block=bi,edge=e))
    endpoints=[row[3] for row in oa[e*2:e*2+2] if row[2]=='primary'];affected=any(n in touched for n in endpoints)
    if affected:res.add('transition_mask_reindex','UNKNOWN',dict(block=bi,edge=e,old=x[4:6].hex(),new=y[4:6].hex(),reason='adjacency order/degree changed; need proven bit-to-turn binding'))
    else:res.check('unaffected_transition_masks_preserved',x[4:6]==y[4:6],dict(block=bi,edge=e))
   if cn[5]>ca[5]:
    res.add('new_transition_masks','UNKNOWN',dict(block=bi,ids=[ca[5],cn[5]-1]))
    res.add('sections_6_7_8_9_semantic_dependencies','UNKNOWN',dict(block=bi,reason='byte preservation does not prove absence of new required references'))
    res.add('external_RT_RL_indexes','UNKNOWN',dict(block=bi,reason='MP0-only inputs cannot validate companion files'))
   for k in [1,3,6,7,8,9]:
    res.check('opaque_section_%d_preserved'%k,ca[k]==cn[k] and old[sa[k]:sa[k+1]]==new[sn[k]:sn[k+1]],dict(block=bi,section=k))
   for k in [0,1]:res.check('existing_coordinate_identity',coa[k]==con[k][:len(coa[k])],dict(block=bi,table=k))
   box=struct.unpack_from('<4i',b,114+bi*24)
   if changed:res.check('new_primary_coordinates_in_bbox',all(box[0]<=x<=box[2] and box[1]<=y<=box[3] for x,y in con[0][len(coa[0]):]),dict(block=bi))
   ja,_,_,linesa=next(geometry_old);jn,_,_,linesn=next(geometry_new);assert ja==jn==bi
   res.check('old_edge_geometry',len(linesn)>=len(linesa) and all(x['points']==y['points'] for x,y in zip(linesa,linesn)),dict(block=bi))
   # Retain the confirmed two-copy secondary-edge signatures. New border edges need remote identity proof.
   for records,coords,oracle,dest in [(ea,coa,oa,borders_old),(en,con,on,borders_new)]:
    for e,x in enumerate(records):
     f,at,opaque,u,v,length=struct.unpack('<5HI',x)
     if f&0x3000:
      points=(coords[int(bool(f&0x1000))][u],coords[int(bool(f&0x2000))][v]);key=(tuple(sorted(points)),length,f&~0x3000,at,opaque)
      dest[key]+=1
   res.add('block_structure','PASS')
  for it in [ga,gb,geometry_old,geometry_new]:
   try:next(it)
   except StopIteration:pass
   else:raise ValueError('unexpected extra blocks')
  res.add('container_stream_extents','PASS')
  res.check('existing_border_copy_signatures',all(borders_new[k]>=v for k,v in borders_old.items()),{})
  added_border=borders_new-borders_old
  if added_border:res.add('new_border_identity','UNKNOWN',dict(signatures=len(added_border),reason='requires unique remote primary-head proof, not coordinates alone'))
  for k,v in borders_new.items():res.check('border_copy_multiplicity',v==2,dict(signature=repr(k),copies=v))
  res.check('inputs_unchanged',sha(Path(original).read_bytes())==report['original_sha256'] and sha(Path(candidate).read_bytes())==report['candidate_sha256'],{})
 except Exception as ex:
  res.add('read_or_structure_error','FAIL',dict(error=type(ex).__name__,detail=str(ex)))
  res.add('uncompleted_checks','UNKNOWN','Processing stopped at the recorded error; later checks were not run.')
 states=[r['status'] for r in res.rules.values()];report['verdict']='FAIL' if 'FAIL' in states else 'UNKNOWN' if 'UNKNOWN' in states else 'PASS';report['hardware_compatibility']='UNKNOWN';report['rule_counts']=dict(collections.Counter(states));return report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('original',type=Path);p.add_argument('candidate',type=Path);p.add_argument('--reader-project',type=Path);p.add_argument('--report',type=Path);a=p.parse_args()
 if a.report and a.report.resolve() in [a.original.resolve(),a.candidate.resolve()]:p.error('--report must not overwrite either input')
 r=validate(a.original,a.candidate,a.reader_project);text=json.dumps(r,indent=2)
 if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(text,encoding='utf-8')
 print(json.dumps({k:r[k] for k in ['verdict','rule_counts','changed_blocks','added_edges','hardware_compatibility']},indent=2))
 return {'PASS':0,'FAIL':1,'UNKNOWN':2}[r['verdict']]
if __name__=='__main__':sys.exit(main())
