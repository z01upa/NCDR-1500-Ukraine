"""Pass A: bounded exact-source inventory; no claim of MP0 code identification."""
from pathlib import Path
import os
import hashlib,json,struct,shutil,importlib.util
HERE=Path(__file__).parent;BASE=HERE.parent
prior=json.loads((BASE/'xref_v4/evidence/firmware_xref.json').read_text())
result={'prior_report_sha256':hashlib.sha256((BASE/'xref_v4/evidence/firmware_xref.json').read_bytes()).hexdigest(),'tools':{n:shutil.which(n) for n in ['analyzeHeadless','ghidra','r2','radare2','llvm-objdump','objdump','java']},'sources':{},'confirmed_mp0_reader_procedures':[]}
root=Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3])) / 'SW'
for name in ['NAVIMAIN.EXE','NK.BIN']:
 path=next(root.rglob(name));d=path.read_bytes();r={'path':str(path),'sha256':hashlib.sha256(d).hexdigest(),'bytes':len(d)}
 if name=='NAVIMAIN.EXE':
  pe=struct.unpack_from('<I',d,60)[0];op=pe+24;ep=struct.unpack_from('<I',d,op+16)[0];base=struct.unpack_from('<I',d,op+28)[0];r.update(machine=hex(struct.unpack_from('<H',d,pe+4)[0]),entry_rva=hex(ep),image_base=hex(base),entry_va=hex(base+ep),entry_file_offset=hex(0x1224),entry_bytes=d[0x1224:0x1264].hex(),interpretation='SH4 PE32; startup/COM client hypothesis; no map parser call path established')
 else:r.update(marker_0x400=d[0x400:0x410].hex(),first_packet_0x410=d[0x410:0x430].hex(),interpretation='Wrapped CE00FF encoded/addressed image; not a directly mapped PE; absence of embedded PE does not prove absence of navigation code')
 result['sources'][name]=r
result['decision']='No established MP0 reader path and no disassembler found on PATH; stop code search at bounded inventory, pivot to Section4 continuation hypothesis.'
(HERE/'evidence/pass_a_binary.json').write_text(json.dumps(result,indent=2))
freeze={'discovery_blocks':list(range(20)),'rule':'For head degree 1..4 use u16 refs at +2 onward. For head degree 5..7 use three u16 refs at +4/+6/+8 then degree-3 u16 refs at +0 onward of next physical Section4 record. Consume/skip that continuation record; do not interpret its first byte as degree. +2 of high-degree head remains opaque. Do not merge nodes by coordinates.','holdout':'blocks>=20 with no main OR secondary coordinate shared with any discovery-block main/secondary coordinate. Conservative coordinate exclusion for leakage prevention only, not node identity. Quarantine excluded neighboring blocks.','verification':'derive exact primary endpoint incidence independently from Section5 index and 0x1000/0x2000 table selectors; compare multisets; compare continuation coverage against old 511/1325 anomalies. No test-driven rule changes.'}
(HERE/'evidence/pass_a_frozen_rule.json').write_text(json.dumps(freeze,indent=2))
print(result['decision']);print('Frozen discovery blocks 0..19 before control pass')
