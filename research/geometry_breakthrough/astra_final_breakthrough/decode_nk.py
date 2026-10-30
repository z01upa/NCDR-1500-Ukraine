#!/usr/bin/env python3
"""Read-only LK841 CE00FF NK.BIN decoder. Python 3.8+, standard library only.
Exit 0: all packets validated; 2: partial/errors. Outputs are always checkpointed.
"""
import argparse, csv, hashlib, json, os, struct, sys
from pathlib import Path

VERSION = 1
PINNED_SHA256 = 'd5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847'

def sha(b): return hashlib.sha256(b).hexdigest()
def atomic_json(p, obj):
    t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(obj,indent=2),encoding='utf-8');os.replace(t,p)

class DecodeError(Exception):
    def __init__(self, reason, cursor, partial):
        super().__init__(reason);self.cursor=cursor;self.partial=bytes(partial)

def decode_packet(data, start, size, max_output=64*1024*1024):
    out=bytearray();cur=start;counts={'literal_tokens':0,'short_matches':0,'long_matches':0}
    if size>max_output:raise DecodeError('declared output exceeds safety limit',cur,out)
    while len(out)<size:
        if cur>=len(data):raise DecodeError('truncated token',cur,out)
        token_offset=cur;t=data[cur];cur+=1
        if t<0x80:
            n=t
            if n==0:raise DecodeError('zero literal token unsupported',token_offset,out)
            if cur+n>len(data):raise DecodeError('truncated literal bytes',cur,out)
            if len(out)+n>size:raise DecodeError('literal exceeds declared output size',token_offset,out)
            out.extend(data[cur:cur+n]);cur+=n;counts['literal_tokens']+=1
        else:
            n=t&0x3f;nb=2 if t&0x40 else 1
            if cur+nb>len(data):raise DecodeError('truncated match distance',cur,out)
            distance=int.from_bytes(data[cur:cur+nb],'little');cur+=nb
            if n==0:raise DecodeError('zero-length match unsupported',token_offset,out)
            if distance==0 or distance>len(out):raise DecodeError('invalid match distance %d at output %d'%(distance,len(out)),token_offset,out)
            if len(out)+n>size:raise DecodeError('match exceeds declared output size',token_offset,out)
            for _ in range(n):out.append(out[-distance])
            counts['long_matches' if nb==2 else 'short_matches']+=1
    return bytes(out),cur,counts

def header(data,off):
    if off+16>len(data) or data[off:off+2]!=b'CE':return None
    hc,addr,size,checksum=struct.unpack_from('<HIII',data,off+2)
    return dict(header_offset=off,payload_offset=off+16,address=addr,declared_size=size,
                declared_checksum=checksum,header_checksum=hc,header_checksum_actual=sum(data[off+4:off+16]))

def next_header(data,start):
    p=data.find(b'CE',start)
    while p>=0:
        h=header(data,p)
        if h and h['header_checksum']==h['header_checksum_actual'] and (h['address']==0 or 0x80000000<=h['address']<0xc0000000) and h['declared_size']<64*1024*1024:return p
        p=data.find(b'CE',p+2)
    return None

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('input',type=Path);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--resume',action='store_true');a=ap.parse_args()
    inp=a.input.resolve();out=a.out.resolve()
    if inp==out or out in inp.parents:raise SystemExit('Output must not contain the original input')
    data=inp.read_bytes();digest=sha(data);out.mkdir(parents=True,exist_ok=True);(out/'packets').mkdir(exist_ok=True)
    report_path=out/'decode_report.json';previous={}
    if report_path.exists():
        if not a.resume:raise SystemExit('Output already has a report; use --resume or a new directory')
        prior=json.loads(report_path.read_text())
        if prior['input_sha256']!=digest or prior.get('decoder_version')!=VERSION:raise SystemExit('Resume input/version mismatch')
        previous={p['header_offset']:p for p in prior['packets']}
    signature=data.find(b'CE00FF\n');report=dict(decoder_version=VERSION,input=str(inp),input_sha256=digest,pinned_hash_matches=digest==PINNED_SHA256,input_size=len(data),signature_offset=signature,packets=[],errors=[],terminator=None)
    if signature<0 or signature+16>len(data):raise SystemExit('CE00FF header not found')
    base,length=struct.unpack_from('<II',data,signature+8);report['image_base']=base;report['image_length']=length
    report['global_byte_7_uninterpreted']=data[signature+7]  # Not established as a checksum; never assume it is one.
    off=signature+16
    while off<len(data):
        h=header(data,off)
        if not h or h['header_checksum']!=h['header_checksum_actual']:
            report['errors'].append(dict(offset=off,reason='invalid packet header/checksum'))
            n=next_header(data,off+1)
            if n is None:break
            report['errors'][-1]['resync_offset']=n;off=n;continue
        if h['address']==0:
            report['terminator']=h;off+=16;break
        h['index']=len(report['packets']);h['file']='packets/%05d_%08x.bin'%(h['index'],h['address'])
        old=previous.get(off);saved=out/h['file']
        if old and old.get('status')=='ok' and saved.exists() and sha(saved.read_bytes())==old.get('sha256'):
            h=old;off=h['end_offset']
        else:
            try:
                decoded,end,counts=decode_packet(data,h['payload_offset'],h['declared_size']);saved.write_bytes(decoded)
                h.update(counts);h.update(actual_size=len(decoded),actual_checksum=sum(decoded)&0xffffffff,end_offset=end,compressed_size=end-h['payload_offset'],sha256=sha(decoded))
                h['status']='ok' if h['actual_checksum']==h['declared_checksum'] else 'checksum_mismatch'
                if h['status']!='ok':report['errors'].append(dict(offset=off,reason='decoded checksum mismatch'))
                off=end
            except DecodeError as e:
                partial=out/(h['file']+'.partial');partial.write_bytes(e.partial)
                h.update(status='decode_error',error=str(e),error_offset=e.cursor,actual_size=len(e.partial),partial_file=str(partial.relative_to(out)))
                report['errors'].append(dict(offset=off,reason=str(e),error_offset=e.cursor))
                n=next_header(data,max(off+16,e.cursor+1));h['resync_offset']=n
                report['packets'].append(h);atomic_json(report_path,report)
                if n is None:break
                off=n;continue
        report['packets'].append(h);atomic_json(report_path,report)
    report['trailing_offset']=off;report['trailing_size']=len(data)-off
    if not report['terminator']:report['errors'].append(dict(offset=off,reason='no zero-address terminator'))
    report['successful_packets']=sum(p.get('status')=='ok' for p in report['packets'])
    report['decoded_bytes']=sum(p.get('actual_size',0) for p in report['packets'] if p.get('status')=='ok')
    report['complete']=not report['errors'] and off==len(data)
    if off<len(data):report['errors'].append(dict(offset=off,reason='trailing bytes preserved in original input',size=len(data)-off))
    report['input_unchanged']=sha(inp.read_bytes())==digest
    atomic_json(report_path,report)
    fields=['index','header_offset','payload_offset','end_offset','address','declared_size','actual_size','compressed_size','declared_checksum','actual_checksum','header_checksum','header_checksum_actual','status','sha256','file','error','error_offset']
    with (out/'packets.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(report['packets'])
    print(json.dumps({k:report[k] for k in ['input_sha256','successful_packets','decoded_bytes','complete','input_unchanged','trailing_size','errors','terminator']},indent=2))
    return 0 if report['complete'] else 2
if __name__=='__main__':sys.exit(main())
