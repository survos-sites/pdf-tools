"""Bounded synchronous operations. Mediary owns queues/retries; results survive restarts."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from PIL import Image

WORKER=Path(__file__).with_name('analysis_worker.py')


def digest(path):
    with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


class AnalysisRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    imagePath: str
    sha256: str=Field(pattern='^[0-9a-f]{64}$')
    altoPath: str | None=None
    textSource: Literal['alto','tesseract','none']='alto'
    tasks: list[Literal['text','ocr','layout','group']]=Field(default=['layout','group'],min_length=1,max_length=4)
    language: str=Field(default='eng',pattern=r'^[a-zA-Z0-9_]+(?:\+[a-zA-Z0-9_]+)*$')
    threshold: float=Field(default=0.25,ge=0.05,le=0.95)
    regionOcr: bool=False

    @model_validator(mode='after')
    def valid(self):
        if self.textSource=='alto' and not self.altoPath:raise ValueError('altoPath is required for supplied ALTO')
        if self.textSource!='alto' and self.altoPath:raise ValueError('altoPath only applies to supplied ALTO')
        if self.textSource=='tesseract' and 'ocr' not in self.tasks:raise ValueError('Tesseract requires an explicit ocr task')
        if self.textSource!='tesseract' and 'ocr' in self.tasks:raise ValueError('ocr task requires textSource=tesseract')
        if self.regionOcr and ('layout' not in self.tasks or self.textSource!='tesseract'):raise ValueError('regionOcr requires layout and Tesseract')
        if 'group' in self.tasks and self.textSource=='none':raise ValueError('Grouping requires text blocks')
        self.tasks=sorted(set(self.tasks))
        return self


class PageLayoutRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    width: int=Field(default=3000,ge=1280,le=5000)
    threshold: float=Field(default=0.25,ge=0.05,le=0.95)


class PageOcrRequest(PageLayoutRequest):
    language: str=Field(default='eng',pattern=r'^[a-zA-Z0-9_]+(?:\+[a-zA-Z0-9_]+)*$')
    layout: bool=True


def atomic(path,value):
    # Must be called under .state lock, including the disk accounting.
    encoded=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
    budget=int(os.getenv('PDFTOOLS_ANALYSIS_BYTES',str(2*1024**3)))
    used=sum(p.stat().st_size for p in path.parent.glob('*.json'))
    old=path.stat().st_size if path.exists() else 0
    if used-old+len(encoded)>budget:raise HTTPException(507,'Analysis storage full; archive results in Mediary/S3 or raise PDFTOOLS_ANALYSIS_BYTES')
    part=path.with_suffix('.tmp')
    with part.open('wb') as stream:
        stream.write(encoded);stream.flush();os.fsync(stream.fileno())
    part.replace(path)


@contextmanager
def lock(path,blocking=True):
    with path.open('a') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:raise HTTPException(429,'Analysis is busy; Mediary should retry',headers={'Retry-After':'5'})
        try:yield f
        finally:fcntl.flock(f,fcntl.LOCK_UN)


class AnalysisService:
    def __init__(self):
        self.root=Path(os.getenv('PDFTOOLS_ANALYSIS_DIR','.cache/pdf-tools-analysis')).resolve()
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.python=os.getenv('PDFTOOLS_ANALYSIS_PYTHON',sys.executable)
        self.model=Path(os.getenv('PDFTOOLS_LAYOUT_MODEL','work/models/layout_model_new.onnx')).resolve()

    def allowed(self,value):
        path=Path(value).resolve()
        roots=[Path(p).resolve() for p in os.getenv('PDFTOOLS_LOCAL_ROOTS','').split(os.pathsep) if p]
        if not any(path.is_relative_to(root) for root in roots):raise HTTPException(403,'Local scan path is not in PDFTOOLS_LOCAL_ROOTS')
        if not path.is_file():raise HTTPException(404,'Local input does not exist')
        if path.stat().st_size>int(os.getenv('PDFTOOLS_MAX_SOURCE_BYTES',str(512*1024**2))):raise HTTPException(413,'Local input exceeds size limit')
        return path

    def capabilities(self):
        runtime={};runtime_error=None
        try:
            probe=subprocess.run([self.python,'-c','import PIL,onnxruntime as o,json; print(json.dumps({"pillow":PIL.__version__,"onnxruntime":o.__version__,"availableBackends":o.get_available_providers()}))'],capture_output=True,text=True,check=True,timeout=10)
            runtime=json.loads(probe.stdout)
        except (OSError,ValueError,subprocess.SubprocessError):runtime_error='Analysis runtime unavailable; run scripts/setup_analysis.sh'
        tess=None
        try:tess=subprocess.run(['tesseract','--version'],capture_output=True,text=True,check=True,timeout=5).stdout.splitlines()[0]
        except (OSError,IndexError,subprocess.SubprocessError):pass
        return {'execution':'synchronous; Mediary owns queued/retry state',
                'layout':{'ready':self.model.is_file() and bool(runtime),'engine':'american-stories-onnx',
                          'backend':'CPUExecutionProvider','modelSha256':digest(self.model) if self.model.is_file() else None,
                          'error':runtime_error or (None if self.model.is_file() else 'Layout model missing; run scripts/setup_analysis.sh')},
                'runtime':runtime,'ocr':{'ready':bool(tess) and bool(runtime),'engine':'tesseract','version':tess,'backend':'cpu'},
                'alto':{'ready':bool(runtime)},'gpuInferenceEnabled':False,
                'concurrency':max(1,int(os.getenv('PDFTOOLS_ANALYSIS_CONCURRENCY','1')))}

    def get(self,key,status=False):
        if not re.fullmatch('[0-9a-f]{64}',key):raise HTTPException(404,'Unknown analysis result')
        path=self.root/f'{key}{".status" if status else ""}.json'
        if not path.is_file():raise HTTPException(404,'Analysis result not found')
        result=json.loads(path.read_text())
        if status and result['status']=='running':
            # A lost service process must not leave a permanently running job.
            try:
                with lock(self.root/f'{key}.lock',False):result['status']='interrupted';result['error']='Worker owner exited; resubmit identical input'
            except HTTPException:pass
        return result

    @contextmanager
    def slot(self):
        slots=max(1,int(os.getenv('PDFTOOLS_ANALYSIS_CONCURRENCY','1')))
        for n in range(slots):
            f=(self.root/f'.slot-{n}').open('a')
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:f.close();continue
            try:yield f
            finally:fcntl.flock(f,fcntl.LOCK_UN);f.close()
            return
        raise HTTPException(429,'Analysis capacity is busy; retry this page',headers={'Retry-After':'5'})

    def analyze(self,request, trusted=False):
        image=Path(request.imagePath) if trusted else self.allowed(request.imagePath)
        alto=Path(request.altoPath) if trusted and request.altoPath else (self.allowed(request.altoPath) if request.altoPath else None)
        if digest(image)!=request.sha256:raise HTTPException(409,'Source SHA-256 does not match the submitted scan')
        try:
            with Image.open(image) as im:
                if im.width*im.height>int(os.getenv('PDFTOOLS_ANALYSIS_MAX_PIXELS','60000000')):raise HTTPException(413,'Scan exceeds analysis pixel limit')
        except (OSError,Image.DecompressionBombError):raise HTTPException(422,'Invalid or oversized scan')
        options=request.model_dump(exclude={'imagePath','altoPath'})
        options['altoSha256']=digest(alto) if alto else None
        needs_model='layout' in request.tasks or 'group' in request.tasks
        if needs_model and not self.model.is_file():raise HTTPException(503,'Layout model missing; run scripts/setup_analysis.sh')
        fingerprint={'workerSha256':digest(WORKER),'modelSha256':digest(self.model) if needs_model else None}
        # Resolve actual interpreter/package identity in the isolated environment without importing heavy models.
        try:
            # Plain OCR uses Pillow + Tesseract. Layout's optional model runtime must
            # not prevent typed PDFs from being transcribed on a lightweight worker.
            packages=['pillow','numpy','onnxruntime'] if needs_model else ['pillow']
            versions=subprocess.run([self.python,'-c','import importlib.metadata as m,json,sys; print(json.dumps({"python":sys.version,"packages":{p:m.version(p) for p in json.loads(sys.argv[1])}}))',json.dumps(packages)],capture_output=True,text=True,check=True,timeout=20)
            fingerprint.update(json.loads(versions.stdout))
            if request.textSource=='tesseract':
                version=subprocess.run(['tesseract','--version'],capture_output=True,text=True,check=True,timeout=10)
                fingerprint['tesseract']=version.stdout.splitlines()[0]
                langs=subprocess.run(['tesseract','--list-langs'],capture_output=True,text=True,check=True,timeout=10).stdout
                directory=re.search(r'"([^"]+)"',langs)
                if not directory:raise ValueError('Cannot identify installed tessdata directory')
                fingerprint['tessdata']={lang:digest(Path(directory[1])/f'{lang}.traineddata') for lang in request.language.split('+')}
        except (OSError,ValueError,subprocess.SubprocessError):raise HTTPException(503,'Analysis runtime or requested Tesseract language unavailable; run setup and verify dependencies')
        threads=max(1,int(os.getenv('PDFTOOLS_ANALYSIS_THREADS','4')));options['threads']=threads
        key=hashlib.sha256(json.dumps([options,fingerprint],sort_keys=True).encode()).hexdigest()
        target=self.root/f'{key}.json';state=self.root/f'{key}.status.json'
        if not trusted:
            with lock(self.root/'.state'):atomic(self.root/f'{key}.source.json',{'path':str(image),'sha256':request.sha256})
        if target.exists():return json.loads(target.read_text()),True
        with lock(self.root/f'{key}.lock',False) as result_lock,self.slot() as slot_lock:
            if target.exists():return json.loads(target.read_text()),True
            def status(value):
                with lock(self.root/'.state'):atomic(state,{'resultId':key,**value})
            previous=json.loads(state.read_text()).get('attempt',0) if state.exists() else 0
            status({'status':'running','attempt':previous+1})
            try:
                with tempfile.TemporaryDirectory(prefix='pdf-analysis-') as tmp:
                    tmp=Path(tmp);source=tmp/('scan'+image.suffix);shutil.copyfile(image,source)
                    job={**options,'imagePath':str(source),'modelPath':str(self.model),'altoPath':None}
                    if alto:
                        shutil.copyfile(alto,tmp/'alto.xml');job['altoPath']=str(tmp/'alto.xml')
                    (tmp/'request.json').write_text(json.dumps(job))
                    env={**os.environ,'OMP_THREAD_LIMIT':str(threads),'OPENBLAS_NUM_THREADS':str(threads)}
                    proc=subprocess.Popen([self.python,str(WORKER),str(tmp/'request.json'),str(tmp/'result.json')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env=env,pass_fds=(result_lock.fileno(),slot_lock.fileno()))
                    try:stdout,stderr=proc.communicate(timeout=int(os.getenv('PDFTOOLS_ANALYSIS_TIMEOUT','300')))
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid,signal.SIGKILL);proc.communicate()
                        raise HTTPException(504,'Page analysis timed out; lower complexity or increase PDFTOOLS_ANALYSIS_TIMEOUT')
                    if proc.returncode:
                        # Worker stderr may include private paths: retain locally, return a bounded actionable class.
                        error=stderr.decode(errors='replace')[-4000:]
                        with lock(self.root/'.state'):atomic(self.root/f'{key}.error.json',{'stderr':error})
                        raise HTTPException(422,'Analysis failed; inspect local resultId.error.json, check scan/ALTO/model compatibility')
                    result=json.loads((tmp/'result.json').read_text())
                result.update(resultId=key,engine=fingerprint,options=options)
                ids=[b['id'] for b in result['blocks']]
                assigned=[i for g in result['groups'] for i in g['blockIds']]+result['unassignedBlockIds']
                if len(set(ids))!=len(ids) or sorted(assigned)!=sorted(ids):raise ValueError('Invalid block coverage in analysis result')
                with lock(self.root/'.state'):atomic(target,result)
                status({'status':'completed','attempt':previous+1})
                return result,False
            except Exception as e:
                status({'status':'failed','attempt':previous+1,'error':e.detail if isinstance(e,HTTPException) else 'Invalid analysis output; inspect worker and retry'})
                if isinstance(e,HTTPException):raise HTTPException(e.status_code,{'resultId':key,'message':e.detail})
                raise HTTPException(422,{'resultId':key,'message':'Invalid analysis output'}) from e
