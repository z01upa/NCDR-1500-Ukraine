exec(open(__file__.replace('index_probe.py','table_probe.py')).read().split('for ext')[0])
for ext in ['MP0','MG3']:
 d=(r/('EUZ.'+ext)).read_bytes();n=struct.unpack_from('<I',d,86)[0]
 for i in range(n):
  a,b,c,e=struct.unpack_from('<iiii',d,114+16*i)
  if not (-18000000<=a<=c<=18000000 and -9000000<=b<=e<=9000000):break
 print(ext,'validboxes',i,'n',n,'transition',114+16*i)
 p=114+16*i
 for j in range(p-32,p+160,16):print(j,d[j:j+16].hex(' '),struct.unpack_from('<IIII',d,j))
