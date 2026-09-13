import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from fastapi import HTTPException
from PIL import Image

from pdf_tools.analysis import AnalysisRequest, AnalysisService, lock
from pdf_tools.analysis_worker import alto, group_blocks, geometry


def test_alto_scales_units_and_retains_source_ids(tmp_path):
    p=tmp_path/'alto.xml';p.write_text('''<alto><Description><MeasurementUnit>inch1200</MeasurementUnit></Description><Layout><Page WIDTH="4000" HEIGHT="8000"><TextBlock ID="B1" HPOS="400" VPOS="800" WIDTH="800" HEIGHT="400"><TextLine ID="L1" HPOS="400" VPOS="800" WIDTH="800" HEIGHT="400"><String ID="W1" CONTENT="Archive" WC=".8" HPOS="400" VPOS="800" WIDTH="800" HEIGHT="400"/></TextLine></TextBlock></Page></Layout></alto>''')
    blocks,transform=alto(p,1000,2000)
    assert blocks[0]['id']=='B1'
    assert blocks[0]['box']==[100,200,200,100]
    assert blocks[0]['lines'][0]['words'][0]['box']==[100,200,200,100]
    assert transform['toOriginalImage']==[.25,0,0,0,.25,0,0,0,1]
    assert blocks[0]['text']=='Archive'


def test_ambiguous_region_ownership_preserves_blocks():
    blocks=[{'id':'a','box':[10,10,10,10]}, {'id':'b','box':[70,70,10,10]}]
    regions=[{'id':'r1','type':'article','box':[0,0,50,50],'confidence':.9},
             {'id':'r2','type':'article','box':[0,0,30,30],'confidence':.8}]
    groups,unassigned=group_blocks(blocks,regions)
    assert groups==[] and unassigned==['a','b']
    groups,unassigned=group_blocks(blocks,regions[:1])
    assert groups[0]['blockIds']==['a'] and unassigned==['b']
    assert groups[0]['reviewed'] is False


def test_requests_do_not_silently_ocr():
    with pytest.raises(ValueError):AnalysisRequest(imagePath='a',sha256='a'*64,textSource='tesseract',tasks=['layout'])
    with pytest.raises(ValueError):AnalysisRequest(imagePath='a',sha256='a'*64,textSource='none',tasks=['group'])


def test_local_input_allowlist_and_checksum(tmp_path,monkeypatch):
    monkeypatch.setenv('PDFTOOLS_ANALYSIS_DIR',str(tmp_path/'results'))
    s=AnalysisService();im=tmp_path/'a.png';Image.new('RGB',(100,200),'white').save(im)
    req=AnalysisRequest(imagePath=str(im),sha256='0'*64,textSource='none',tasks=['layout'])
    with pytest.raises(HTTPException) as e:s.analyze(req)
    assert e.value.status_code==403
    monkeypatch.setenv('PDFTOOLS_LOCAL_ROOTS',str(tmp_path))
    with pytest.raises(HTTPException) as e:s.analyze(req)
    assert e.value.status_code==409
    with pytest.raises(HTTPException):s.get('../outside')


def test_slot_release_and_stale_status(tmp_path,monkeypatch):
    monkeypatch.setenv('PDFTOOLS_ANALYSIS_DIR',str(tmp_path));monkeypatch.setenv('PDFTOOLS_ANALYSIS_CONCURRENCY','1')
    s=AnalysisService()
    with s.slot():
        with pytest.raises(HTTPException) as e:
            with s.slot():pass
        assert e.value.status_code==429
    with s.slot():pass
    key='a'*64;(tmp_path/f'{key}.status.json').write_text(json.dumps({'status':'running'}))
    assert s.get(key,True)['status']=='interrupted'
    with lock(tmp_path/f'{key}.lock'):
        assert s.get(key,True)['status']=='running'


def test_worker_preserves_pixel_space(tmp_path):
    path=tmp_path/'scan.png';Image.new('RGB',(100,200),'white').save(path)
    source=hashlib.sha256(path.read_bytes()).hexdigest()
    job={'imagePath':str(path),'sha256':source,'tasks':['text'],'textSource':'none'}
    request=tmp_path/'req.json';request.write_text(json.dumps(job));out=tmp_path/'out.json'
    subprocess.run([sys.executable,'-m','pdf_tools.analysis_worker',str(request),str(out)],check=True)
    result=json.loads(out.read_text())
    assert result['width']==100 and result['height']==200
    assert result['coordinateSpace']=='original-image-pixels'
    assert result['transforms']['analysisToOriginal']==[1,0,0,0,1,0,0,0,1]
