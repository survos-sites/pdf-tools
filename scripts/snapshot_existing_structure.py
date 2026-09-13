"""Read existing claims and match exact sourceHash; no service calls or vault writes."""
import argparse
import json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('dataset',type=Path);p.add_argument('--output',type=Path,default=Path('work/pilot/existing-structure.json'));a=p.parse_args()
requests=[json.loads(l) for l in (a.dataset/'structure/requests.jsonl').read_text().splitlines()]
claims=[json.loads(l) for l in (a.dataset/'ai/claims.jsonl').read_text().splitlines()];rows=[]
for page in [1,2,3,4,12,19,21,25]:
    req=next(r for r in requests if r['context']['periodicalPage']['pageIndex']==page-1)
    matches=[c for c in claims if c['predicate']=='ai:periodicalStructure' and c['value'].get('sourceHash')==req['sourceHash']]
    if not matches:continue
    v=matches[-1]['value'];rows.append({'page':page,'sourceHash':req['sourceHash'],'model':v.get('model'),'groups':v['groups'],'unassignedBlockIds':v['unassignedBlockIds'],'coverageWarnings':v.get('coverageWarnings'),'note':'Existing semantic grouping of supplied ALTO. This is NOT Mistral OCR.'})
a.output.write_text(json.dumps(rows,indent=2));print(f'Matched {len(rows)} pages, no paid requests')
