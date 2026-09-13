"""Manually chosen page-2 reading-order anchors; missing anchors fail, not silently excluded."""
import json
from pathlib import Path
from score_newspaper_pilot import inside

anchors={'coal-head':[44,87,324,52],'coal-deck':[45,145,160,42],'coal-body-start':[44,201,160,40],'coal-second-column':[210,145,158,42],
         'photo-head':[380,94,300,27],'photo-caption':[375,562,302,22],
         'stolen-head':[534,897,158,32],'stolen-body':[536,984,154,98]}
pairs=[['coal-head','coal-deck'],['coal-deck','coal-body-start'],['coal-body-start','coal-second-column'],['photo-head','photo-caption'],['stolen-head','stolen-body']]
rows=[]
for mode in ['alto','alto-layout','tesseract','region-ocr']:
    r=json.loads(Path(f'work/pilot/results/p02-{mode}.json').read_text());words=[w for b in r['blocks'] for l in b['lines'] for w in l['words']];positions={}
    for name,box in anchors.items():
        box=[v*s for v,s in zip(box,[r['width']/1200,r['height']/1681]*2)]
        found=[i for i,w in enumerate(words) if inside(w,box)];positions[name]=min(found) if found else None
    for a,b in pairs:
        rows.append({'mode':mode,'before':a,'after':b,'firstWordIndexA':positions[a],'firstWordIndexB':positions[b],
                     'pass':positions[a] is not None and positions[b] is not None and positions[a]<positions[b]})
Path('work/pilot/order-scores.json').write_text(json.dumps({'page':2,'previewDimensions':[1200,1681],'anchors':anchors,'pairs':rows,
 'limitations':'Five anchor pairs on one page; noisy recognized marks may count as anchor presence. Does not establish full page reading order. Continued article links are absent in every local result and existing page-scoped structure claims.'},indent=2))
for m in ['alto','alto-layout','tesseract','region-ocr']:print(m,sum(r['pass'] for r in rows if r['mode']==m),'/5')
