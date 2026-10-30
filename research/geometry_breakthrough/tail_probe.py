from decoder import *
for name in ['MP0_0','MG3_0']:
 b=(Path(__file__).parent/'evidence'/f'{name}.bin').read_bytes();s,n,size=struct.unpack_from('<HHH',b,40);d=b[s:];print(name,s,n,size,len(d),'halves equal',d[:len(d)//2]==d[len(d)//2:]);print('middle',d[len(d)//2:len(d)//2+80].hex(' '));offs=struct.unpack_from('<'+str(n+1)+'H',d);print('table',offs[:8],offs[-8:], 'monotone',all(x<=y for x,y in zip(offs,offs[1:])))
 if all(x<=y for x,y in zip(offs,offs[1:])):
  for k in range(8):print(k,offs[k],offs[k+1],d[offs[k]:offs[k+1]].hex(' '))
