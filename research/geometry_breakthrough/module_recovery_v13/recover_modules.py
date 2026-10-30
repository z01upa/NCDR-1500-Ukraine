#!/usr/bin/env python3
"""Read-only CE 2.x ROM module recovery. No NK packet decompression.
Format reference: gweslab/extract-wince-rom @ 5eedf30beced801fa753b9ab693cd06bb5068133
winmob_extract/pe/e32.py and compress.py. Strict independent implementation:
never silently clamp malformed references or replace missing input with zeros.
"""
import argparse, hashlib, json, struct
from pathlib import Path

def sha(b): return hashlib.sha256(b).hexdigest()
def u32(b,o=0):return struct.unpack_from('<I',b,o)[0]
def ce_blocks(raw):
    size=int.from_bytes(raw[:3],'little');count=size//4096+1;start=3*(count+1)
    if start>len(raw):raise ValueError('short compressed index')
    ends=[int.from_bytes(raw[3*i:3*i+3],'little') for i in range(1,count+1)]
    out=bytearray();blocks=[]
    for end in ends:
        if not start<=end<=len(raw):raise ValueError('invalid compressed block bounds')
        b=raw[start:end];p=0;dst=bytearray();want=min(4096,size-len(out))
        while p<len(b) and len(dst)<want:
            flag=b[p];p+=1
            for bit in range(8):
                if len(dst)==want:break
                if p>=len(b):raise ValueError('truncated token')
                t=b[p];p+=1
                if not flag&(1<<bit):dst.append(t);continue
                lo=t&15;hi=t>>4
                if lo==1:n=2;src=len(dst)-hi-2
                else:
                    if p>=len(b):raise ValueError('truncated match')
                    src=(b[p]<<4)|hi;p+=1
                    if lo==0:
                        if p>=len(b):raise ValueError('truncated length')
                        n=b[p]+17;p+=1
                    else:n=lo+1
                if not 0<=src<len(dst) or len(dst)+n>want:raise ValueError('invalid match bounds')
                for i in range(n):dst.append(dst[src+i])
        if len(dst)!=want or p!=len(b):raise ValueError('block length/input consumption mismatch')
        blocks.append(dict(start=start,end=end,decoded_size=len(dst)))
        out.extend(dst);start=end
    if start!=len(raw) or len(out)!=size:raise ValueError('section length mismatch')
    return bytes(out),blocks

class Image:
    def __init__(self,root):
        self.root=root;self.meta=json.loads((root/'address_map.json').read_text());self.b=(root/'addressed_image.bin').read_bytes()
        assert sha(self.b)==self.meta['sha256'];self.base=self.meta['base']
    def read(self,va,n):
        if n<0 or va<self.base or va+n>self.meta['end']:raise ValueError('address outside image')
        for r in self.meta['regions']:
            if not r['present'] and va<r['end'] and va+n>r['start']:raise ValueError('address intersects hole')
        return self.b[va-self.base:va-self.base+n]

def recover(image,m,out):
    out.mkdir(parents=True,exist_ok=True);e=image.read(m['e32_va'],100)
    n,flags,entry,vbase,major,minor,stack,vsize,subsys=struct.unpack_from('<HHIIHHIIH',e)
    assert n==5 and subsys==9 and major==2 and minor==12
    dirs=[dict(index=i,rva=u32(e,28+i*8),size=u32(e,32+i*8)) for i in range(9)]
    result=dict(toc=m,e32_layout='CE2: subsystem +0x18, directories +0x1c',imageflags=flags,entry_rva=entry,link_base=vbase,version=[major,minor],virtual_size=vsize,directories=dirs,sections=[])
    (out/'e32_rom.bin').write_bytes(e);(out/'o32_rom.bin').write_bytes(image.read(m['o32_va'],24*n))
    payloads=[]
    for i in range(n):
        vs,rva,ps,dp,real,fl=struct.unpack('<6I',image.read(m['o32_va']+24*i,24))
        assert rva+vs<=vsize
        raw=image.read(dp,ps if fl&0x2000 else min(ps,vs));fn='section_%d'%i;(out/(fn+'.stored.bin')).write_bytes(raw)
        s=dict(index=i,rva=rva,virtual_size=vs,stored_size=ps,storage_va=dp,runtime_va=real,flags=fl,compressed=bool(fl&0x2000),stored_sha256=sha(raw),stored_bytes_read=len(raw),excluded_alignment_bytes=ps-len(raw),executable=bool(fl&0x20000000))
        try:
            if s['compressed']:data,blocks=ce_blocks(raw);s['compression_blocks']=blocks
            else:data=raw
            assert len(data)<=max(ps,vs)
            (out/(fn+'.bin')).write_bytes(data);s.update(status='recovered',decoded_size=len(data),sha256=sha(data),virtual_zero_tail=max(0,vs-len(data)))
            payloads.append((s,data))
        except Exception as ex:s.update(status='blocked',error=str(ex))
        result['sections'].append(s)
    def read(rva,n):
        for s,b in payloads:
            off=rva-s['rva']
            if 0<=off and off+n<=len(b):return b[off:off+n]
        raise ValueError('RVA unavailable %x +%x'%(rva,n))
    def string(rva):
        b=bytearray()
        for i in range(4096):
            c=read(rva+i,1)
            if c==b'\0':return b.decode('ascii')
            b+=c
        raise ValueError('unterminated string')
    result['exports']=[];result['imports']=[]
    try:
        rv=dirs[0]['rva'];h=struct.unpack('<IIHHIIIIIII',read(rv,40));_,_,_,_,name,ordinal,nf,nn,ft,nt,ot=h
        assert nf<65536 and nn<=nf
        names={struct.unpack('<H',read(ot+i*2,2))[0]:string(u32(read(nt+i*4,4))) for i in range(nn)}
        result['export_module_name']=string(name)
        for i in range(nf):
            r=u32(read(ft+i*4,4));s=next((s for s in result['sections'] if s['rva']<=r<s['rva']+s['virtual_size']),None)
            result['exports'].append(dict(ordinal=ordinal+i,name=names.get(i),rva=r,runtime_va=s['runtime_va']+r-s['rva'] if s else None,forwarder=string(r) if rv<=r<rv+dirs[0]['size'] else None))
    except Exception as ex:result['exports_error']=str(ex)
    try:
        rv=dirs[1]['rva']
        for idx in range(100):
            oft,stamp,chain,name,ft=struct.unpack('<5I',read(rv+idx*20,20))
            if not any([oft,stamp,chain,name,ft]):break
            mod=dict(name=string(name),original_thunk_rva=oft,iat_rva=ft,symbols=[])
            for k in range(10000):
                val=u32(read((oft or ft)+k*4,4))
                if val==0:break
                sym=dict(iat_rva=ft+k*4,bound_value=u32(read(ft+k*4,4)))
                if val&0x80000000:sym['ordinal']=val&0xffff
                else:sym['name']=string(val+2)
                mod['symbols'].append(sym)
            result['imports'].append(mod)
    except Exception as ex:result['imports_error']=str(ex)
    # Stored and runtime locations are distinct; never equate TOC load with link base.
    result['entry_runtime_va']=next(s['runtime_va']+entry-s['rva'] for s in result['sections'] if s['rva']<=entry<s['rva']+s['virtual_size'])
    (out/'module.json').write_text(json.dumps(result,indent=2))
    return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--decoded',type=Path,default=Path(__file__).resolve().parent.parent/'astra_final_breakthrough/decoded');args=ap.parse_args()
    root=Path(__file__).resolve().parent;im=Image(args.decoded);c=next(c for c in im.meta['rom_candidates'] if c['romhdr_va']==0x8d2f66cc)
    assert c['nummods']==154 and im.read(c['signature_va'],4)==b'ECEC' and u32(im.read(c['signature_va']+4,4))==c['romhdr_va']
    results=[]
    for m in c['modules']:
        if m['name'].lower() in ['navigationrem.dll','nmicore_ce.dll']:results.append(recover(im,m,root/'modules'/m['name']))
    report=dict(image_sha256=sha(im.b),romhdr_va=c['romhdr_va'],romhdr_sha256=sha(im.read(c['romhdr_va'],84)),modules=results)
    (root/'recovery.json').write_text(json.dumps(report,indent=2))
    for r in results:print(r['toc']['name'],[(s['index'],s['status'],s.get('decoded_size'),s.get('error')) for s in r['sections']],len(r['exports']),len(r['imports']),r.get('imports_error'))
if __name__=='__main__':main()
