#!/usr/bin/env python3
"""Verify persisted decoder output, checkpoint this run and create its transfer ZIP."""
import csv,hashlib,json,struct,zipfile
from pathlib import Path
root=Path(__file__).resolve().parent;d=root/'decoded';r=json.loads((d/'decode_report.json').read_text());m=json.loads((d/'address_map.json').read_text())
src=Path(r['input']);raw=src.read_bytes();assert hashlib.sha256(raw).hexdigest()==r['input_sha256']
cur=r['signature_offset']+16;total=0
for p in r['packets']:
 assert p['header_offset']==cur
 h=raw[cur:cur+16];assert h[:2]==b'CE'
 hc,addr,n,ck=struct.unpack_from('<HIII',h,2)
 assert hc==sum(h[4:]) and addr==p['address'] and n==p['declared_size'] and ck==p['declared_checksum']
 b=(d/p['file']).read_bytes();assert len(b)==n and sum(b)&0xffffffff==ck and hashlib.sha256(b).hexdigest()==p['sha256'] and p['status']=='ok'
 total+=len(b);cur=p['end_offset']
assert cur==r['terminator']['header_offset'] and cur+16==len(raw)
assert r['complete'] and not r['errors'] and r['input_unchanged']
assert total==m['mapped_bytes'] and not m['overlapping_packets']
assert hashlib.sha256((d/'addressed_image.bin').read_bytes()).hexdigest()==m['sha256']
verified=dict(packets_verified=len(r['packets']),bytes_verified=total,all_packet_headers_valid=True,all_decoded_checksums_valid=True,all_saved_sha256_valid=True,compressed_stream_contiguous=True,terminator_at_eof=True,source_unchanged=True,address_image_sha256_valid=True,overlapping_packets=0)
(root/'verification.json').write_text(json.dumps(verified,indent=2))
c=m['rom_candidates'][0];targets=[x for x in c['modules'] if x['name'].lower() in ('navigationrem.dll','nmicore_ce.dll')]
with (root/'modules.csv').open('w',newline='',encoding='utf-8') as f:
 w=csv.DictWriter(f,fieldnames=list(c['modules'][0]));w.writeheader();w.writerows(c['modules'])
with (root/'address_regions.csv').open('w',newline='',encoding='utf-8') as f:
 w=csv.DictWriter(f,fieldnames=['start','end','size','present']);w.writeheader();w.writerows(m['regions'])
(root/'README.md').write_text('''# Autonomous NK.BIN decoder — LK841
Python 3.8+; standard library only; Windows and macOS; no Codex or paid API.

macOS:
```sh
python3 decode_nk.py "/path/to/original/NK.BIN" --out decoded_new
python3 analyze_image.py decoded_new
```
Windows PowerShell:
```powershell
py -3 decode_nk.py "D:\\NCDR\\NK.BIN" --out decoded_new
py -3 analyze_image.py decoded_new
```
Resume an interrupted run with the same input and output:
```sh
python3 decode_nk.py "/path/to/NK.BIN" --out decoded_new --resume
```
Exit 0 means complete packet decoding with verified sizes/checksums and terminator at EOF; exit 2 means partial/errors. Never overwrite the input. A changed input hash prevents resuming. Successful packet files and partial failures survive; exact error offsets are in decode_report.json. Original offsets and addresses in CSV/JSON are decimal integers; convert with hex() when needed.

Included `decoded/` is the actual full run, not a test fixture. It contains independently checksummed packet files, a single addressed image, and explicit hole/coverage metadata. Holes in addressed_image.bin are filled with zero for storage only: do not interpret them as recovered original bytes. The source NK.BIN is deliberately excluded from the ZIP; use the pinned original identified in FORMAT_RULES.md. No module executable has yet been reconstructed.
''',encoding='utf-8')
(root/'FORMAT_RULES.md').write_text(f'''# Confirmed on the complete LK841 image
Input: {len(raw):,} bytes. SHA-256 `{r['input_sha256']}`.

- The LK wrapper occupies the first 0x400 bytes. Signature `CE00FF\\n` starts at 0x400; byte +7 is 0x0B, meaning unresolved (not a verified checksum).
- Global LE32 +8 = image base 0x{r['image_base']:08X}; LE32 +12 = span 0x{r['image_length']:X}.
- Packet stream begins at 0x410. Header is 16 bytes: ASCII CE at +0; LE16 header sum at +2; LE32 destination VA at +4; LE32 decoded byte count at +8; LE32 decoded additive checksum at +12.
- Header sum equals sum of its 12 bytes at +4..+15. This holds for every decoded packet and the terminal header.
- A token below 0x80 copies that many following literal bytes.
- Token 0x80..0xBF: length = token & 0x3F, then an unsigned 8-bit backward distance.
- Token 0xC0..0xFF: length = token & 0x3F, then an unsigned 16-bit little-endian backward distance.
- Match copying is byte-by-byte and permits overlap. Dictionary starts empty for each packet. No length or distance bias is added.
- Decoding stops exactly at the declared output length. The consumed-input cursor is the next packet boundary; compressed length is not guessed from CE string hits.
- Packet checksum is sum(decoded bytes) modulo 2^32. All {len(r['packets'])} packet sizes and checksums passed. Zero literal/zero-length match/zero distance were not encountered and are rejected rather than assigned speculative semantics.
- Zero-address header at 0x{r['terminator']['header_offset']:X} ends the stream exactly at EOF. Its +8 value is 0x{r['terminator']['declared_size']:08X} (entry-point interpretation still unverified); +12 is zero. It has no data payload.
- Decoded destination ranges do not overlap. {m['mapped_bytes']:,} bytes mapped across 0x{m['base']:08X}..0x{m['end']:08X} (end exclusive); {m['holes']:,} bytes are unrepresented gaps, tracked explicitly.
- Recovered image contains ROM signature ECEC and a ROMHDR/TOC candidate at 0x{c['romhdr_va']:08X}: {c['nummods']} complete TOC rows, all names resolve through recovered address coverage. The candidate CPU field is zero: this does not establish SH4 code validity. Target module e32/o32/load pointers are preserved in modules.csv; DLL code has not been extracted or validated.

Provenance: the transferred v10 report explicitly left CE+2 semantics unresolved. This run established the packet rules through exact whole-image consumption, decoded lengths and all additive checksums. No prior algorithm implementation was available in that transfer. No claim is made that this format applies to every Windows CE image.
''',encoding='utf-8')
lines=['# CHECKPOINT — 2026-10-29','Stopped after the requested decoding/address-map/ROMHDR stage at the user’s instruction.','',f'FULL PACKET DECODE VERIFIED: {len(r["packets"])} / {len(r["packets"])}; {total:,} decoded bytes; 0 packet errors; exact EOF terminator; original hash unchanged.',f'Address map: 0x{m["base"]:08X}..0x{m["end"]:08X}, {m["holes"]:,} explicit holes, no overlaps.',f'ROMHDR/TOC candidate: 0x{c["romhdr_va"]:08X}, {c["nummods"]} modules, all names mapped; CPU field zero.', '']
for t in targets:lines.append(f'- {t["name"]}: TOC index {t["index"]}; e32=0x{t["e32_va"]:08X}, o32=0x{t["o32_va"]:08X}, load=0x{t["load_va"]:08X}, recorded file size={t["size"]}.')
lines+=['','No DLL executable/code section was extracted; no SH4 disassembly, routing reader, Section 4/5 semantics or direction flags are claimed. No MP0, SQLite, Writer, Manager, GUI or earlier research was changed.','', 'Artifacts: decode_nk.py; analyze_image.py; decoded/decode_report.json; decoded/packets.csv; decoded/packets/*.bin; decoded/addressed_image.bin; decoded/address_map.json; address_regions.csv; modules.csv; verification.json.','',f'Original input remains at: {src}', 'The transfer ZIP contains only this new result directory, excluding this finalize helper and the original image.']
(root/'CHECKPOINT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(root/'NEXT_STEP.md').write_text('''# Next task for Astra on Mac
Start from decoded/address_map.json and modules.csv; do not rerun topology_v6 or rediscover packet compression.

1. Open the ROMHDR/TOC candidate and validate the e32_rom/o32_rom structures for NavigationRem.dll and nmicore_ce.dll using only present address regions. Confirm section counts, mapped bounds, flags and per-section physical/virtual sizes. The zero CPU field requires independent architecture evidence.
2. Extract actual section bytes through this address map. If individual ROM sections are additionally compressed, identify and validate that layer separately. Preserve actual addresses and distinguish missing bytes/BSS from stored zeros.
3. Reconstruct analysis executables only after headers/sections are coherent; keep raw mapped section bytes beside the reconstruction. Disassemble SH4 code, verify aligned entry points, branch targets, literal pools and calls. Names alone are not code evidence.
4. Then locate EUZ.MP0 references and actual readers of Section 4/5; use existing topology_v6 node/edge format as a control, without rerunning topology statistics. Do not infer direction/routing semantics from strings alone.

No further analysis was started because the user requested stopping after the decoding/address-map stage. Full packet decoding is complete, so the current blocker is validation/extraction of executable ROM modules, not NK packet compression.
''',encoding='utf-8')
files=sorted(p for p in root.rglob('*') if p.is_file() and p.name not in ('MANIFEST_SHA256.json','finalize.py') and '__pycache__' not in p.parts)
manifest={str(p.relative_to(root)):dict(size=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files}
(root/'MANIFEST_SHA256.json').write_text(json.dumps(manifest,indent=2))
archive=root.parent/'NCDR_ASTRA_FINAL_BREAKTHROUGH_20261029.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
 for p in files+[root/'MANIFEST_SHA256.json']:z.write(p,root.name+'/'+str(p.relative_to(root)))
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
s=hashlib.sha256(archive.read_bytes()).hexdigest();archive.with_suffix('.zip.sha256').write_text(s+'  '+archive.name+'\n')
print(json.dumps(verified,indent=2));print('ZIP',archive);print('SIZE',archive.stat().st_size);print('SHA256',s)
