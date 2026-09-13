"""Isolated, network-free page analysis. Stdout is a JSON protocol, never logs."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from PIL import Image

VERSION = 'newspaper-ledger-1'
CLASSES = ['article', 'author', 'cartoon_or_advertisement', 'headline', 'image_caption',
           'masthead', 'newspaper_header', 'page_number', 'photograph', 'table']


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def geometry(box, width, height):
    x, y, w, h = box
    return {'box': [x, y, w, h], 'bboxNormalized': [x/width, y/height, (x+w)/width, (y+h)/height]}


def alto(path, width, height):
    raw = Path(path).read_bytes()
    if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
        raise ValueError('ALTO DTD/entities are not supported')
    root = ET.fromstring(raw)
    page = root.find('.//{*}Page')
    aw, ah = float(page.attrib['WIDTH']), float(page.attrib['HEIGHT'])
    sx, sy = width/aw, height/ah
    def box(e):
        return [float(e.get(k, '0'))*s for k,s in zip(('HPOS','VPOS','WIDTH','HEIGHT'), (sx,sy,sx,sy))]
    blocks = []
    for bi,b in enumerate(page.findall('.//{*}TextBlock')):
        lines = []
        for li,l in enumerate(b.findall('.//{*}TextLine')):
            words = [{'id':w.get('ID',f'w{wi}'), 'text':w.get('CONTENT',''),
                      **geometry(box(w),width,height), 'confidence':float(w.get('WC')) if w.get('WC') else None}
                     for wi,w in enumerate(l.findall('{*}String'))]
            lines.append({'id':l.get('ID',f'l{li}'), 'text':' '.join(w['text'] for w in words),
                          **geometry(box(l),width,height), 'words':words})
        blocks.append({'id':b.get('ID',f'b{bi}'), 'type':'text', 'text':'\n'.join(l['text'] for l in lines),
                       **geometry(box(b),width,height), 'lines':lines, 'textSource':'supplied-alto'})
    return blocks, {'measurementUnit':root.findtext('.//{*}MeasurementUnit'), 'width':aw,'height':ah,
                    'toOriginalImage':[sx,0,0,0,sy,0,0,0,1]}


def tesseract(image, language, psm, prefix='t', offset=(0,0), source_size=None):
    data = io.BytesIO(); image.save(data, format='PNG')
    proc = subprocess.run(['tesseract','stdin','stdout','-l',language,'--psm',str(psm),'tsv'],
                          input=data.getvalue(), capture_output=True, timeout=180, check=True)
    width,height = source_size or image.size
    groups = {}
    for row in csv.DictReader(io.StringIO(proc.stdout.decode()), delimiter='\t', quoting=csv.QUOTE_NONE):
        if row['level'] != '5' or not row['text'].strip(): continue
        bid = f"{prefix}-b{row['block_num']}-p{row['par_num']}"
        lid = bid+f"-l{row['line_num']}"
        box = [int(row['left'])+offset[0],int(row['top'])+offset[1],int(row['width']),int(row['height'])]
        word = {'id':lid+f"-w{row['word_num']}", 'text':row['text'], **geometry(box,width,height),
                'confidence':max(0,float(row['conf']))/100}
        groups.setdefault(bid,{}).setdefault(lid,[]).append(word)
    def union(items):
        boxes = [i['box'] for i in items]
        x=min(b[0] for b in boxes); y=min(b[1] for b in boxes)
        return [x,y,max(b[0]+b[2] for b in boxes)-x,max(b[1]+b[3] for b in boxes)-y]
    blocks=[]
    for bid,ls in groups.items():
        lines=[{'id':lid,'text':' '.join(w['text'] for w in ws),'words':ws,
                **geometry(union(ws),width,height)} for lid,ws in ls.items()]
        blocks.append({'id':bid,'type':'text','text':'\n'.join(l['text'] for l in lines),
                       'textSource':'tesseract','lines':lines,**geometry(union(lines),width,height)})
    return blocks


def detect(image, model, threshold, threads):
    """YOLOv8 ONNX, explicit CPU backend; retain real probabilities and invert letterboxing."""
    import numpy as np
    import onnxruntime as ort
    options=ort.SessionOptions(); options.intra_op_num_threads=threads; options.inter_op_num_threads=1
    session=ort.InferenceSession(model,sess_options=options,providers=['CPUExecutionProvider'])
    spec=session.get_inputs()[0]; size=spec.shape[-1]
    if not isinstance(size,int): raise ValueError('Expected fixed-size square YOLO model')
    w,h=image.size; scale=min(size/w,size/h)
    rw,rh=round(w*scale),round(h*scale); left,top=(size-rw)//2,(size-rh)//2
    canvas=Image.new('RGB',(size,size),(114,114,114)); canvas.paste(image.resize((rw,rh)),(left,top))
    tensor=np.asarray(canvas,dtype=np.float32).transpose(2,0,1)[None]/255
    rows=session.run(None,{spec.name:tensor})[0][0].T
    scores=rows[:,4:].max(axis=1); labels=rows[:,4:].argmax(axis=1)
    keep=np.where(scores>=threshold)[0]; keep=keep[np.argsort(-scores[keep])]
    xy=rows[:,:4].copy(); xy[:,:2]-=xy[:,2:]/2; xy[:,2:]+=xy[:,:2]
    selected=[]
    while len(keep) and len(selected)<500:
        i=int(keep[0]);selected.append(i); rest=keep[1:]
        if not len(rest): break
        inter=np.maximum(0,np.minimum(xy[i,2:],xy[rest,2:])-np.maximum(xy[i,:2],xy[rest,:2])).prod(axis=1)
        area=(xy[:,2:]-xy[:,:2]).prod(axis=1)
        iou=inter/np.maximum(area[i]+area[rest]-inter,1e-9)
        keep=rest[(iou<0.4)|(labels[rest]!=labels[i])]
    regions=[]
    for i in selected:
        x0,y0,x1,y1=xy[i]; x0=max(0,(float(x0)-left)*w/rw);x1=min(w,(float(x1)-left)*w/rw)
        y0=max(0,(float(y0)-top)*h/rh);y1=min(h,(float(y1)-top)*h/rh)
        if x1<=x0 or y1<=y0: continue
        regions.append({'type':CLASSES[int(labels[i])],'confidence':float(scores[i]),
                        **geometry([x0,y0,x1-x0,y1-y0],w,h)})
    regions.sort(key=lambda r:(round(r['box'][1],3),round(r['box'][0],3),r['type']))
    for i,r in enumerate(regions):r['id']=f'r{i+1}'
    return regions


def group_blocks(blocks,regions):
    """Conservative candidate associations, never infer an obituary from geometry."""
    ownership={r['id']:[] for r in regions}; unassigned=[]
    for block in blocks:
        x,y,w,h=block['box'];matches=[]
        for r in regions:
            rx,ry,rw,rh=r['box']
            overlap=max(0,min(x+w,rx+rw)-max(x,rx))*max(0,min(y+h,ry+rh)-max(y,ry))
            if overlap/max(w*h,1)>=0.85:matches.append(r)
        # Overlapping detections represent uncertainty, not two copies of the text.
        if len(matches)==1: ownership[matches[0]['id']].append(block['id'])
        else:unassigned.append(block['id'])
    groups=[]
    for r in regions:
        ids=ownership[r['id']]
        if not ids:continue
        kind={'article':'article','image_caption':'illustration_caption','photograph':'illustration_caption'}.get(r['type'],'uncertain')
        groups.append({'id':'g-'+r['id'],'kind':kind,'title':'','blockIds':ids,'regionIds':[r['id']],
                       'reason':f"Candidate {r['type']} detection; blocks have >=85% coverage by exactly one region. Not reviewed; headlines/continuations are not joined.",
                       'confidence':r['confidence'],'reviewed':False,'obituary':None})
    return groups,unassigned


def run(job):
    start=time.monotonic(); image=Image.open(job['imagePath']).convert('RGB');w,h=image.size
    if digest(job['imagePath'])!=job['sha256']:raise ValueError('Source SHA-256 changed before execution')
    tasks=job['tasks'];regions=[];blocks=[];transform=None
    if 'layout' in tasks or 'group' in tasks:
        regions=detect(image,job['modelPath'],job['threshold'],job['threads'])
    if job['textSource']=='alto':
        if digest(job['altoPath'])!=job['altoSha256']:raise ValueError('ALTO checksum changed')
        blocks,transform=alto(job['altoPath'],w,h)
    elif 'ocr' in tasks:
        if job.get('regionOcr'):
            for r in regions:
                if r['type'] in ('photograph',):continue
                x,y,rw,rh=r['box'];x,y=int(x),int(y);right,bottom=min(w,int(x+rw+1)),min(h,int(y+rh+1))
                blocks.extend(tesseract(image.crop((x,y,right,bottom)),job['language'],6,r['id'],(x,y),(w,h)))
        else:blocks=tesseract(image,job['language'],3)
    groups,unassigned=group_blocks(blocks,regions) if 'group' in tasks else ([],[b['id'] for b in blocks])
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    child=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    unit=1 if sys.platform=='darwin' else 1024
    return {'schemaVersion':VERSION,'sourceSha256':job['sha256'],'width':w,'height':h,
            'coordinateSpace':'original-image-pixels','boxFormat':'xywh',
            'transforms':{'analysisToOriginal':[1,0,0,0,1,0,0,0,1],'deskewDegrees':0,'rotationDegrees':0,'alto':transform},
            'blocks':blocks,'regions':regions,'readingOrder':[b['id'] for b in blocks],
            'readingOrderBasis':'supplied-alto-order' if job['textSource']=='alto' else ('region-top-to-bottom-unreviewed' if job.get('regionOcr') else 'tesseract-order-unreviewed'),
            'warnings':(['OCR returned no text; review or retry with regionOcr'] if 'ocr' in tasks and not blocks else []) + (['Region OCR may omit text outside detections and duplicate text in overlapping detections; source scan is authoritative'] if job.get('regionOcr') else []),
            'groups':groups,'unassignedBlockIds':unassigned,'text':'\n\n'.join(b['text'] for b in blocks),
            'metrics':{'seconds':time.monotonic()-start,'workerPeakBytes':peak*unit,'childPeakBytes':child*unit,
                       'conservativePeakBytes':(peak+child)*unit}}


if __name__=='__main__':
    try:
        import signal
        # Also bound an orphan after its service parent exits; kill OCR children too.
        signal.signal(signal.SIGALRM, lambda *_: os.killpg(os.getpgrp(), signal.SIGKILL))
        signal.alarm(int(os.getenv('PDFTOOLS_ANALYSIS_TIMEOUT','300')) + 5)
        job=json.loads(Path(sys.argv[1]).read_text());result=run(job)
        Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
    except Exception as e:
        print(f'{type(e).__name__}: {e}',file=sys.stderr);sys.exit(1)
