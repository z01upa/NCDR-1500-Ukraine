from decoder_v1_unsigned_secondary import *
import math,statistics
out=Path(__file__).parent;ratios=[];errors=[];samples=[];fail=[];total=0;vertices=0;within=0;shape_edges=0
for i,box,off,c,raw in blocks((ROOT/'EUZ.MP0').read_bytes(),True):
 try:lines=decode_mp0_polylines(raw)
 except (ValueError,struct.error) as e:fail.append([i,str(e)]);continue
 for row in lines:
  points=row['coordinates_integer'];dist=sum(math.hypot((xx-x)*math.cos((y+yy)/200000*math.pi/180),yy-y)*1.11195 for (x,y),(xx,yy) in zip(points,points[1:]));length=row['length_field']*.3048
  total+=1;vertices+=len(points);shape_edges+=bool(row['flags']&0x8000)
  if length>10:ratios.append(dist/length)
  err=abs(dist-length);errors.append(err);within+=err<=max(5,length*.02)
  if i<3 and row['edge']<3:samples.append(dict(row,block=i,source_offset=off,calculated_m=dist,length_field_times_0_3048=length))
summary={'blocks_passed':2956-len(fail),'failures':fail,'edges':total,'vertices':vertices,'shape_edges':shape_edges,'within_5m_or_2percent':within,'ratio_median':statistics.median(ratios),'ratio_p01':sorted(ratios)[len(ratios)//100],'ratio_p99':sorted(ratios)[len(ratios)*99//100],'error_median_m':statistics.median(errors),'external_geography_verified':False}
print(summary);(out/'evidence/polyline_audit.json').write_text(json.dumps(summary,indent=2));(out/'evidence/polyline_candidates.json').write_text(json.dumps(samples,indent=2))

