"""All-block consolidation. Emits complete logical adjacency and endpoint evidence."""
from topology_decoder import *
from collections import Counter,defaultdict
from dataclasses import asdict
import hashlib,json,gzip
HERE=Path(__file__).parent;OUT=HERE/'evidence'
def run():
 OUT.mkdir(exist_ok=True);data=SOURCE.read_bytes();before=hashlib.sha256(data).hexdigest()
 if before!=EXPECTED:raise ValueError('source changed from known corpus')
 totals=Counter();degrees=Counter();anomalies=defaultdict(list);blocks_report=[];borders=defaultdict(list);examples={};problems=[];owners_all=set();local_digest=hashlib.sha256();expected_digest=hashlib.sha256()
 with gzip.open(OUT/'logical_adjacency.jsonl.gz','wt',encoding='utf8') as output:
  for bi,b in read_blocks(data):
   s,c=layout(b);section=b[s[4]:s[5]];nodes=decode_section4(section,c[5]);heads={n.physical_id:n for n in nodes};owners={n.continuation_id:n.physical_id for n in nodes if n.continuation_id is not None};owners_all.update((bi,n) for n in owners)
   restored=encode_section4(nodes);same=restored==section
   if not same:problems.append({'block':bi,'error':'section4_noop'})
   totals.update(blocks=1,physical_records=c[4],logical_nodes=len(nodes),continuations=len(owners),high_degree_heads=sum(n.degree>4 for n in nodes),edge_records=c[5],noop_blocks=int(same))
   actual=Counter((n.physical_id,e) for n in nodes for e in n.edges);oracle=endpoint_oracle(b);expected=Counter((index,e) for e,side,table,index in oracle if table=='primary')
   missing=expected-actual;extra=actual-expected
   if missing or extra:problems.append({'block':bi,'missing':list(missing.items()),'extra':list(extra.items())})
   totals['missing_primary_memberships']+=sum(missing.values());totals['extra_or_foreign_primary_memberships']+=sum(extra.values());totals['primary_endpoint_sides']+=sum(expected.values());totals['secondary_endpoint_sides']+=sum(t=='secondary' for _,_,t,_ in oracle)
   for item in sorted(actual.items()):local_digest.update(repr((bi,item)).encode())
   for item in sorted(expected.items()):expected_digest.update(repr((bi,item)).encode())
   for n in nodes:
    degrees[n.degree]+=1;totals['repeated_memberships_within_node']+=len(n.edges)-len(set(n.edges))
    output.write(json.dumps({'block':bi,'physical_node_id':n.physical_id,'logical_ordinal':n.logical_id,'degree':n.degree,'continuation_record':n.continuation_id,'edge_ids':n.edges},separators=(',',':'))+'\n')
    if n.degree not in examples:
     examples[n.degree]={'block':bi,'physical_node':n.physical_id,'degree':n.degree,'edges':n.edges,'record_hex':section[n.physical_id*10:(n.physical_id+n.physical_span)*10].hex()};(OUT/f'fixture_degree{n.degree}.bin').write_bytes(b)
   for n,owner in owners.items():
    low=section[10*n]&15;group='119_apparent_zero' if low==0 else ('511_old_mismatches' if low<=4 else '1325_apparent_high')
    anomalies[group].append({'block':bi,'record':n,'owner':owner,'apparent_low_nibble':low});totals['continuations_targeted_by_primary_edges']+=any(index==n and table=='primary' for _,_,table,index in oracle)
   for e in range(c[5]):
    rows=oracle[2*e:2*e+2]
    if rows[0][2:]==rows[1][2:]:totals['same_table_same_index_self_loops']+=1
    primary=sum(row[2]=='primary' for row in rows);totals['edges_with_'+str(primary)+'_primary_sides']+=1
   coords=None
   for e,side,table,index in oracle:
    if table!='secondary':continue
    if coords is None:coords=coordinate_tables(b)
    at=s[5]+14*e;flags,attr,opaque,u,v,length=struct.unpack_from('<5HI',b,at);types=[bool(flags&4096),bool(flags&8192)];indices=[u,v];points=[coords[int(t)][n] for t,n in zip(types,indices)]
    key=(tuple(sorted(points)),length,flags&~0x3000,attr,opaque)
    # Add edge once even if both sides were secondary.
    if any(r['block']==bi and r['edge']==e for r in borders[key]):continue
    borders[key].append({'block':bi,'edge':e,'types':types,'indices':indices,'points':points,'primary_heads_valid':all(t or n in heads for t,n in zip(types,indices))})
   blocks_report.append({'block':bi,'physical_records':c[4],'logical_nodes':len(nodes),'continuations':len(owners),'edge_records':c[5],'section4_bytes':len(section),'section4_sha256':hashlib.sha256(section).hexdigest(),'rebuilt_section4_sha256':hashlib.sha256(restored).hexdigest()})
 border_links=[];border_counts=Counter()
 for key,rows in borders.items():
  border_counts['copy_group_size_'+str(len(rows))]+=1
  if len(rows)!=2 or rows[0]['block']==rows[1]['block']:problems.append({'error':'ambiguous_border_copy','rows':rows});continue
  for src,dst in [rows,rows[::-1]]:
   for side,t in enumerate(src['types']):
    if not t:continue
    candidates=[j for j,typ in enumerate(dst['types']) if not typ and dst['points'][j]==src['points'][side]]
    if len(candidates)!=1 or not dst['primary_heads_valid']:problems.append({'error':'remote_head','src':src,'dst':dst});continue
    target=dst['indices'][candidates[0]];border_links.append({'source':[src['block'],src['edge'],'AB'[side],'secondary',src['indices'][side]],'target':[dst['block'],dst['edge'],'primary',target]});border_counts['resolved_secondary_sides']+=1
 old=json.loads((HERE.parent/'topology_v3/evidence/node_link_validation.json').read_text())['low_degree_identity_adjacency']['all_mismatch_records'];old_ids={(r['block'],r['node']) for r in old};now_ids={(r['block'],r['record']) for r in anomalies['511_old_mismatches']}
 if old_ids!=now_ids:problems.append({'error':'old511_exact_set'})
 if len(border_links)!=totals['secondary_endpoint_sides']:problems.append({'error':'unresolved_secondary_sides'})
 if totals['primary_endpoint_sides']+totals['secondary_endpoint_sides']!=2*totals['edge_records']:problems.append({'error':'edge_side_total'})
 after=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
 if before!=after:problems.append({'error':'source_changed'})
 r={'status':'DONE_ADJACENCY_ONLY' if not problems else 'INCOMPLETE','source':str(SOURCE),'source_sha256_before':before,'source_sha256_after':after,'counts':dict(totals),'logical_degree_counts':dict(degrees),'legacy_cohorts':{k:len(v) for k,v in anomalies.items()},'old511_exact_identity_set_equal':old_ids==now_ids,'border':dict(border_counts),'unique_edges_under_verified_two_copy_rule':totals['edge_records']-len(borders),'adjacency_membership_sha256':local_digest.hexdigest(),'section5_primary_membership_sha256':expected_digest.hexdigest(),'problems':problems,'examples':examples,'scope':'Full endpoint adjacency for exact EU MP0; no routing semantics, direction, costs or insertion safety claim'}
 (OUT/'acceptance.json').write_text(json.dumps(r,indent=2));(OUT/'block_checks.json').write_text(json.dumps(blocks_report,indent=2));(OUT/'legacy_cohorts.json').write_text(json.dumps(anomalies,indent=2));(OUT/'remote_endpoint_links.json').write_text(json.dumps(border_links,separators=(',',':')))
 print(json.dumps({k:v for k,v in r.items() if k!='examples'},indent=2));return r
if __name__=='__main__':run()
