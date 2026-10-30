from decoder import *
from encoder import encode_shapes
from independent_verify import independent_blocks
import copy
HERE=Path(__file__).parent;d=(ROOT/'EUZ.MP0').read_bytes();count=0;target=None
for i,box,offset,cs,raw in blocks(d,True):
 encoded=encode_shapes(raw,decode_mp0_polylines(raw));assert encoded==raw;count+=1
 if i==886:target=(i,box,offset,cs,raw)
i,box,off,cs,raw=target;lines=decode_mp0_polylines(raw);mutated=copy.deepcopy(lines);x,y=mutated[1]['coordinates_integer'][1];mutated[1]['coordinates_integer'][1]=(x+5,y)
changed=encode_shapes(raw,mutated);assert changed!=raw
(HERE/'evidence/MP0_886.bin').write_bytes(raw);(HERE/'evidence/MP0_886_modified.bin').write_bytes(changed)
# Single-block test envelope, not a claimed device-compatible map.
z=zlib.compress(changed,9);header=bytearray(d[:114]);struct.pack_into('<II',header,86,1,len(z));struct.pack_into('<H',header,112,1)
envelope=bytes(header)+struct.pack('<4iIHH',*box,142,len(changed),len(z))+b'\0'*4+z
path=HERE/'evidence/experimental_one_block.MP0';path.write_bytes(envelope)
read=list(independent_blocks(path));decoded=read[0][3]
assert len(decoded)==len(mutated)
for a,b in zip(decoded,mutated):assert a['points']==b['coordinates_integer']
assert decoded[1]['points'][1]==(x+5,y)
assert encode_shapes(changed,lines)==raw
report={'all_original_blocks_byte_exact_shape_roundtrip':count,'confirmed_block':886,'modified_edge':1,'vertex_index':1,'before':[x,y],'after':[x+5,y],'independent_readback_all_edges_passed':len(decoded),'restore_original_exact':True,'raw_original_sha256':hashlib.sha256(raw).hexdigest(),'raw_modified_sha256':hashlib.sha256(changed).hexdigest(),'scope':'shape-tail encoder and isolated single-block compressed envelope; no full map writer; length attributes unchanged; not for deployment'}
(HERE/'evidence/encoder_roundtrip.json').write_text(json.dumps(report,indent=2));print(report)
