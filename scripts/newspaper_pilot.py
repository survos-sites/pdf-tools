"""Evaluate already-acquired scans. No ingestion, registration, networking or paid calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pdf_tools.analysis import AnalysisService, AnalysisRequest


def main():
    p=argparse.ArgumentParser();p.add_argument('--scans',type=Path,required=True);p.add_argument('--alto',type=Path,required=True)
    p.add_argument('--pages',default='1,2,3,4,12,19,21,25');p.add_argument('--output',type=Path,default=Path('work/pilot/results'))
    p.add_argument('--modes',default='alto,alto-layout,tesseract,region-ocr');p.add_argument('--retries',type=int,default=1)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('PDFTOOLS_LOCAL_ROOTS',os.pathsep.join([str(args.scans.resolve()),str(args.alto.resolve())]))
    service=AnalysisService();manifest=json.loads((args.scans/'scans-manifest.json').read_text());rows=[]
    for number in map(int,args.pages.split(',')):
        item=next(r for r in manifest if r['page']==number)
        for mode in args.modes.split(','):
            raw={'imagePath':str(args.scans/item['file']),'sha256':item['sha256']}
            if mode in ('alto','alto-layout'):raw.update(textSource='alto',altoPath=str(args.alto/f'{number}.xml'),tasks=['group'] if mode=='alto-layout' else ['layout'])
            elif mode=='tesseract':raw.update(textSource='tesseract',tasks=['ocr'])
            elif mode=='region-ocr':raw.update(textSource='tesseract',tasks=['layout','ocr','group'],regionOcr=True)
            else:raise ValueError('Unknown mode')
            # ALTO-only explicitly parses supplied evidence, without model inference.
            if mode=='alto':raw['tasks']=['text']
            start=time.monotonic()
            for attempt in range(args.retries+1):
                try:
                    result,cached=service.analyze(AnalysisRequest(**raw));break
                except Exception as e:
                    if attempt==args.retries:
                        row={'page':number,'mode':mode,'error':str(e),'seconds':time.monotonic()-start};rows.append(row);print(json.dumps(row),flush=True);result=None
            if result is None:continue
            dest=args.output/f'p{number:02}-{mode}.json';dest.write_text(json.dumps(result,ensure_ascii=False,indent=2))
            row={'page':number,'mode':mode,'resultId':result['resultId'],'cached':cached,'wallSeconds':time.monotonic()-start,
                 **result['metrics'],'blocks':len(result['blocks']),'words':sum(len(l['words']) for b in result['blocks'] for l in b['lines']),
                 'regions':len(result['regions']),'groups':len(result['groups']),'unassigned':len(result['unassignedBlockIds'])}
            rows.append(row);print(json.dumps(row),flush=True)
            (args.output/'benchmark.json').write_text(json.dumps(rows,indent=2))
    (args.output/'benchmark.json').write_text(json.dumps(rows,indent=2))

if __name__=='__main__':main()
