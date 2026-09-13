"""Real subprocess timeout, retry and durable cache replay. Uses a pre-acquired scan, never paid work."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from pdf_tools.analysis import AnalysisRequest, AnalysisService, digest

p=argparse.ArgumentParser();p.add_argument('scan',type=Path);p.add_argument('--output',type=Path,default=Path('work/pilot/recovery.json'));a=p.parse_args()
os.environ['PDFTOOLS_LOCAL_ROOTS']=str(a.scan.resolve().parent)
os.environ['PDFTOOLS_ANALYSIS_DIR']=str(a.output.resolve().parent/'recovery-cache')
r=AnalysisRequest(imagePath=str(a.scan.resolve()),sha256=digest(a.scan),textSource='tesseract',tasks=['ocr'])
os.environ['PDFTOOLS_ANALYSIS_TIMEOUT']='1';s=AnalysisService();started=time.monotonic()
try:s.analyze(r);raise AssertionError('Expected cold timeout; remove recovery-cache before rerunning')
except HTTPException as e:
    assert e.status_code==504,e
    key=e.detail['resultId'];failed=s.get(key,True);assert failed['status']=='failed'
timeout_seconds=time.monotonic()-started
os.environ['PDFTOOLS_ANALYSIS_TIMEOUT']='300';result,cached=AnalysisService().analyze(r)
assert result['resultId']==key and not cached
status=AnalysisService().get(key,True);assert status['attempt']==2 and status['status']=='completed'
start=time.monotonic();again,hit=AnalysisService().analyze(r)
assert hit and again==result
out={'timeoutStatus':failed,'timeoutWallSeconds':timeout_seconds,'retryStatus':status,'sameResultIdAfterRetry':True,'restartCacheHit':hit,'restartCacheSeconds':time.monotonic()-start,'ocrWords':sum(len(l['words']) for b in result['blocks'] for l in b['lines'])}
a.output.write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
