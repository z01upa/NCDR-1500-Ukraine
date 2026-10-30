import struct,re,hashlib,subprocess,csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; T=ROOT/'tools/POISoN'; O=ROOT/'research/poison'; O.mkdir(exist_ok=True)
def pe(path):
 b=path.read_bytes(); peoff=struct.unpack_from('<I',b,0x3c)[0]; fh=peoff+4; n=struct.unpack_from('<H',b,fh+2)[0]; op=struct.unpack_from('<H',b,fh+16)[0]; opt=fh+20; ep=struct.unpack_from('<I',b,opt+16)[0]; base=struct.unpack_from('<I',b,opt+28)[0]; image=struct.unpack_from('<I',b,opt+56)[0]; ts=struct.unpack_from('<I',b,fh+4)[0]; sect=[]; sh=opt+op
 for i in range(n):
  q=sh+40*i; name=b[q:q+8].rstrip(b'\0').decode('latin1'); vs,va,rs,ro=struct.unpack_from('<IIII',b,q+8); ch=struct.unpack_from('<I',b,q+36)[0];sect.append((name,va,vs,ro,rs,ch))
 return b,ts,ep,base,image,sect
def strings(b,unicode=False):
 pat=(rb'(?:[ -~]{5,})' if not unicode else rb'(?:[ -~]\x00){4,}')
 out=[]
 for m in re.finditer(pat,b): out.append((m.start(),m.group().decode('utf-16le' if unicode else 'latin1','replace')))
 return out
def rva(off,sects):
 for n,va,vs,ro,rs,ch in sects:
  if ro<=off<ro+rs:return va+off-ro
 return ''
def main():
 metas=[]; allstr=[]
 for fn in ('poison.exe','patch.exe'):
  b,ts,ep,base,image,sects=pe(T/fn); metas.append((fn,ts,ep,base,image,sects,len(b)))
  for enc in (False,True):
   for off,s in strings(b,enc):
    rv=rva(off,sects); allstr.append({'file':fn,'file_offset':f'0x{off:X}','rva':f'0x{rv:X}' if rv!='' else '','encoding':'UTF-16LE' if enc else 'ASCII','text':s})
 with (O/'poison_strings.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['file','file_offset','rva','encoding','text']);w.writeheader();w.writerows(allstr)
 # imports via objdump static output
 with (O/'imports.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['file','dll','function']);w.writeheader()
  for fn in ('poison.exe','patch.exe'):
   txt=subprocess.check_output(['objdump','-p',str(T/fn)],text=True,errors='replace');dll=''
   for line in txt.splitlines():
    if 'DLL Name:' in line:dll=line.split('DLL Name:',1)[1].strip()
    elif re.match(r'\s+\d+\s+\S',line):w.writerow({'file':fn,'dll':dll,'function':line.strip().split()[-1]})
 with (O/'pe_metadata.txt').open('w') as f:
  for fn,ts,ep,base,image,sects,size in metas:
   f.write(f'{fn}\nSHA256={hashlib.sha256((T/fn).read_bytes()).hexdigest()}\nPE32 i386; timestamp=0x{ts:08X}; image_base=0x{base:X}; entry_rva=0x{ep:X}; entry_va=0x{base+ep:X}; image_size=0x{image:X}; file_size={size}\n')
   for x in sects:f.write('section name=%s RVA=0x%X virtual=0x%X raw_off=0x%X raw=0x%X chars=0x%X\n'%x)
   f.write('No export/resource/debug directories reported by objdump PE data directories. Symbols and relocations stripped.\n\n')
 for fn in ('lng_rel.tbl','voice.lst'):
  b=(T/fn).read_bytes(); (O/(fn+'.hex')).write_text(b.hex(' '))
 with (O/'function_map.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['component','evidence','address_or_status']);w.writeheader()
  rows=[('entry','PE entry point','poison.exe 0x00401240; patch.exe 0x00401240'),('file_io','msvcrt fopen/fread/fseek/fwrite imports','imported; callers require disassembly'),('compression','no zlib/inflate/deflate imports','likely statically linked or custom; not resolved statically here'),('coordinate','5555555/MULCOORD constant scan','not yet uniquely identified'),('writer','fwrite/fseek imports in poison.exe','writer path not uniquely recovered'),('patch','small PE with fopen/fread/fwrite and MessageBoxA','database patch utility likely; exact transformation unresolved')]
  for a,b,c in rows:w.writerow({'component':a,'evidence':b,'address_or_status':c})
 with (O/'COMPRESSION01_RE.md').open('w') as f:f.write('# Compression 0x01 static review\n\nNo decoder is claimed. The executable has no imported zlib/inflate/deflate symbols; static inspection must continue through internal call graphs and bit-level loops before a safe reimplementation is attempted.\n')
 with (O/'WRITER_RE.md').open('w') as f:f.write('# Writer static review\n\n`poison.exe` imports C stdio file I/O (`fopen`, `fread`, `fseek`, `fwrite`, `fflush`, `fclose`) and allocation/memory routines. This establishes file-based read/write capability, but does not by itself prove in-place versus rebuild behavior.\n')
 with (O/'POISON_RE.md').open('w') as f:f.write('# POISoN static reverse-engineering checkpoint\n\nBoth files are PE32 i386 GUI binaries with stripped symbols. Metadata, imports, strings, and auxiliary file bytes were extracted without execution. No compression-0x01 decoder, coordinate conversion routine, or relocation strategy is confirmed by this pass.\n')
 (O/'auxiliary_files.md').write_text('# Auxiliary files\n\n`lng_rel.tbl` is 96 bytes of binary data; `voice.lst` is 1482 bytes and contains a text/binary voice list. Their record grammars and references require further static cross-reference analysis.\n')
 state=ROOT/'research/PROJECT_STATE.md'; state.open('a').write('\n## Phase 15 checkpoint\n\n- Static PE metadata, imports, strings, and auxiliary file snapshots were extracted for POISoN and patch; neither executable was run.\n- No compression-0x01 decoder, coordinate routine, database writer strategy, or relocation behavior is confirmed yet.\n')
if __name__=='__main__':main()
