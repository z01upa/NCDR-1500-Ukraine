from decoder import *
b=(Path(__file__).parent/'evidence/MG3_0.bin').read_bytes();pairs=list(struct.iter_unpack('<HH',b[:44]));pts,r=decode_runs(b,46,pairs[1][0],pairs[0][1]); print('points',pts[:10])
for s in [2,4,5,10]:
 start,n=pairs[s];end=pairs[s+1][0] if s<10 else len(b);stride=(end-start)//n
 print('section',s,start,n,end,'stride',stride)
 for i in range(10):print(i,b[start+i*stride:start+(i+1)*stride].hex(' '),list(struct.unpack('<'+'H'*(stride//2),b[start+i*stride:start+(i+1)*stride])) if stride%2==0 else '')
