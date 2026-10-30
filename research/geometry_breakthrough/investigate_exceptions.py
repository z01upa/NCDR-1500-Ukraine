from independent_verify import *
r=json.loads((HERE/'evidence/independent_validation.json').read_text());rows=r['primary_exceptions'];out=[]
for row in rows:
 p=row['points'];last=[p[-1][0]-p[-2][0],p[-1][1]-p[-2][1]]
 out.append({'block':row['block'],'edge':row['edge'],'flags_hex':hex(row['flags']),'measured_m':row['measured_haversine_m'],'feet_m':row['feet_m'],'last_delta_integer':last,'last_delta_outside_i16':any(not -32768<=v<=32767 for v in last),'vertex_count':len(p),'interpretation':'long-edge encoding/semantics unresolved; same flags do not by themselves prove ferry' if row['flags']==0x834c else 'short-segment length/shape discrepancy remains unresolved','full_evidence':'independent_validation.json'})
(HERE/'evidence/eleven_primary_exceptions.json').write_text(json.dumps(out,indent=2));print('exceptions',len(out),'shared_flags',sum(x['flags_hex']=='0x834c' for x in out),'large_final_delta',sum(x['last_delta_outside_i16'] for x in out))
