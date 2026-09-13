"""Small manually traced target set. Word/text boxes are diagnostics, never article truth."""
import json
from pathlib import Path


def iou(a,b):
    x,y,w,h=a;u,v,s,t=b
    overlap=max(0,min(x+w,u+s)-max(x,u))*max(0,min(y+h,v+t)-max(y,v))
    return overlap/max(1,w*h+s*t-overlap)


def union(boxes):
    if not boxes:return [0,0,0,0]
    x=min(b[0] for b in boxes);y=min(b[1] for b in boxes)
    return [x,y,max(b[0]+b[2] for b in boxes)-x,max(b[1]+b[3] for b in boxes)-y]


def candidates(r,kind):
    if kind in ('blocks','regions'):return [{'label':b['id'],'kind':b['type'],'box':b['box']} for b in r[kind]]
    blocks={b['id']:b['box'] for b in r['blocks']}
    return [{'label':g.get('id',g.get('title')),'kind':g['kind'],'box':union([blocks[i] for i in g['blockIds'] if i in blocks])} for g in r['groups']]


def main():
    base=Path('work/pilot/results');gold=json.loads(Path('benchmarks/newspaper/boundaries.json').read_text())
    alto=json.loads((base/'p02-alto.json').read_text());mistral=next(r for r in json.loads(Path('work/pilot/existing-structure.json').read_text()) if r['page']==2)
    sources={m:candidates(json.loads((base/f'p02-{m}.json').read_text()),'blocks') for m in ['alto','tesseract']}
    for mode in ['alto-layout','region-ocr']:
        r=json.loads((base/f'p02-{mode}.json').read_text());sources[mode+'-groups']=candidates(r,'groups')
    sources['local-detections']=candidates(json.loads((base/'p02-alto-layout.json').read_text()),'regions')
    sources['existing-mistral-structure']=candidates({**alto,'groups':mistral['groups']},'groups');rows=[]
    for g in gold['regions']:
        box=[v*s for v,s in zip(g['box'],[alto['width']/gold['previewWidth'],alto['height']/gold['previewHeight']]*2)]
        for name,items in sources.items():
            best=max(items,key=lambda c:iou(box,c['box']),default={'box':[0,0,0,0]})
            score=iou(box,best['box']);rows.append({'target':g['label'],'kind':g['kind'],'referenceBox':box,'source':name,'best':best,'iou':score,'kindAndIoU50':score>=.5 and best.get('kind')==g['kind']})
    Path('work/pilot/boundary-scores.json').write_text(json.dumps({'method':gold['method'],'rows':rows},indent=2))
    for name in sources:
        r=[x for x in rows if x['source']==name];print(name, 'mean best IoU',round(sum(x['iou'] for x in r)/len(r),3),'IoU>=.5',sum(x['iou']>=.5 for x in r),'kind+IoU>=.5',sum(x['kindAndIoU50'] for x in r))

if __name__=='__main__':main()
