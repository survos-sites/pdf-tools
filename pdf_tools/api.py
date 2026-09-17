import hashlib
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .cache import Cache, Source
from .engine import execute
from .analysis import AnalysisService, AnalysisRequest, PageLayoutRequest, PageOcrRequest
import tempfile
import io
from PIL import Image
from .analysis import digest


def install(app: FastAPI):
    @asynccontextmanager
    async def lifespan(app):
        app.state.cache = Cache()
        app.state.analysis = AnalysisService()
        # PyMuPDF must not run in the server's thread pool or share open Documents.
        with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
            app.state.pdf_pool = pool
            yield
    app.router.lifespan_context = lifespan
    app.add_middleware(CORSMiddleware, allow_origins=os.getenv('PDFTOOLS_CORS_ORIGINS', '*').split(','),
                       allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type'])

    def _public_read(path: str, method: str) -> bool:
        """Paths served without a bearer token.

        IIIF reads are public because a browser has to fetch them directly: a
        viewer loads info.json and then tiles from the page itself, so any token
        guarding them would have to be embedded in the HTML, which is not a
        token any more. Registration (POST /v1/files) stays authenticated, so
        nothing can ask this service to fetch a URL of its own choosing — the
        only renderable documents are ones an authenticated caller registered.
        A file id is 32 hex characters and is only discoverable from a page that
        already publishes the image.
        """
        if path in ('/health', '/demo', '/demo/') or path.startswith('/demo/'):
            return True

        return method in ('GET', 'HEAD') and path.startswith('/iiif/')

    @app.middleware('http')
    async def authentication(request, call_next):
        import secrets
        token = os.getenv('PDFTOOLS_TOKEN')
        if token and request.method != 'OPTIONS' and not _public_read(request.url.path, request.method):
            if not secrets.compare_digest(request.headers.get('authorization', ''), f'Bearer {token}'):
                return JSONResponse({'detail': 'Bearer token required'}, status_code=401)
        return await call_next(request)

    def run(path, operation, **params):
        try:
            return app.state.pdf_pool.submit(execute, str(path), operation, params).result()
        except IndexError as e:
            raise HTTPException(404, str(e))
        except (ValueError, RuntimeError) as e:
            raise HTTPException(422, str(e))

    def register(source):
        cache = app.state.cache
        with cache.lease():
            file_id = cache.handle(source)
            try:
                old = cache.record(file_id)
            except HTTPException as e:
                if e.status_code != 404:
                    raise
                old = None
            if old and not source.sha256:
                # A known file: refresh how its bytes are reached (a new signed URL, or an S3
                # reference instead of one) without fetching them. The pinned checksum still guards
                # the next download, when an evicted file is read again. Re-registering 45k
                # RappNews pages to switch them to S3 otherwise re-downloaded every one.
                record = {**old, 'source': source.model_dump()}
                cache.save(file_id, record)
                return {'id': file_id, 'sha256': record['sha256'], 'bytes': record['bytes'], **record['info']}
            # Refresh credentials without changing identity or already validated bytes.
            path, checksum = cache.acquire(source, old['sha256'] if old else None)
            if source.sha256 and checksum != source.sha256:
                raise HTTPException(409, 'Checksum does not match registered revision')
            try:
                info = old['info'] if old else run(path, 'info')
            except HTTPException:
                path.unlink(missing_ok=True)
                raise
            record = {'source': source.model_dump(), 'sha256': checksum, 'bytes': path.stat().st_size, 'info': info}
            cache.save(file_id, record)
            return {'id': file_id, 'sha256': checksum, 'bytes': record['bytes'], **info}

    def operation(file_id, op, **params):
        cache = app.state.cache
        with cache.lease():
            record = cache.record(file_id)
            params.setdefault('nativeDpi', int(os.getenv('PDFTOOLS_NATIVE_DPI', '300')))
            params.setdefault('maxPixels', int(os.getenv('PDFTOOLS_MAX_PIXELS', '20000000')))
            key = hashlib.sha256(json.dumps([record['sha256'], 'v1', op, params], sort_keys=True).encode()).hexdigest()
            artifact = cache.root / 'bytes' / (key + ('.image' if op == 'render' else '.json'))
            if artifact.exists():
                artifact.touch()
                data = artifact.read_bytes()
            else:
                path, _ = cache.acquire(Source(**record['source']), record['sha256'])
                result = run(path, op, **params)
                data = result if isinstance(result, bytes) else json.dumps(result).encode()
                cache.reserve(len(data), keep=(path.name,))
                part = artifact.with_suffix('.part')
                part.write_bytes(data)
                part.replace(artifact)
            return data, hashlib.sha256(data).hexdigest()

    def reply(file_id, op, request, media='application/json', **params):
        data, etag = operation(file_id, op, **params)
        # A read is keyed by the source checksum and the request parameters, so a given URL's bytes
        # never change: cache it hard, in the browser and in front of the service. Purge the CDN if a
        # source is ever replaced under the same identity (that is what `revision` is for).
        headers = {'ETag': f'"{etag}"', 'Cache-Control': 'public, max-age=31536000, immutable'}
        if request.headers.get('if-none-match') == headers['ETag']:
            return Response(status_code=304, headers=headers)
        return Response(data, media_type=media, headers=headers)

    app.state.register_pdf = register
    app.state.pdf_operation = operation

    @app.get('/v1/analysis/capabilities')
    def analysis_capabilities():
        return app.state.analysis.capabilities()

    @app.post('/v1/analysis', summary='Analyze an allowlisted local scan; synchronous, idempotent')
    def analyze_scan(body: AnalysisRequest):
        result, cached = app.state.analysis.analyze(body)
        return JSONResponse(result, headers={'X-Cache': 'HIT' if cached else 'MISS', 'Location': '/v1/results/'+result['resultId']})

    @app.get('/v1/results/{result_id}')
    def analysis_result(result_id: str):
        return app.state.analysis.get(result_id)

    @app.get('/v1/results/{result_id}/image.jpg')
    def analysis_preview(result_id: str):
        app.state.analysis.get(result_id)  # Validate ID and existing result before constructing paths.
        source_file = app.state.analysis.root/f'{result_id}.source.json'
        if not source_file.is_file(): raise HTTPException(404, 'No retained local scan reference; use PDF page image API')
        source = json.loads(source_file.read_text())
        path = app.state.analysis.allowed(source['path'])
        if digest(path) != source['sha256']: raise HTTPException(409, 'Original scan changed')
        with Image.open(path) as im:
            im.thumbnail((1800,2400)); out = io.BytesIO(); im.convert('RGB').save(out,format='JPEG',quality=88)
        return Response(out.getvalue(),media_type='image/jpeg')

    @app.get('/v1/results/{result_id}/status')
    def analysis_status(result_id: str):
        return app.state.analysis.get(result_id, status=True)

    def analyze_pdf_page(file_id, page, body, ocr=False):
        # Render completes under the PDF lease; model execution happens after it is released.
        info = json.loads(operation(file_id, 'page', page=page)[0])
        data = operation(file_id, 'render', page=page, format='png', quality='default', size=f'{body.width},')[0]
        with tempfile.TemporaryDirectory(prefix='pdf-page-') as tmp:
            path = Path(tmp)/'page.png'; path.write_bytes(data)
            tasks = ['layout'] if not ocr else (['layout','ocr','group'] if body.layout else ['ocr'])
            request = AnalysisRequest(imagePath=str(path), sha256=hashlib.sha256(data).hexdigest(),
                textSource='tesseract' if ocr else 'none', tasks=tasks, threshold=body.threshold,
                language=body.language if ocr else 'eng', regionOcr=ocr and body.layout)
            result, cached = app.state.analysis.analyze(request, trusted=True)
        result = {**result, 'pdf': {'fileId': file_id, 'page': page, 'widthPt': info['widthPt'],
                   'heightPt': info['heightPt'], 'rotation': info['rotation'],
                   'coordinateNote': 'Boxes are in the rendered input image; normalized boxes map to displayed PDF/IIIF.'}}
        return JSONResponse(result, headers={'X-Cache': 'HIT' if cached else 'MISS'})

    @app.post('/v1/files/{file_id}/pages/{page}/layout')
    def page_layout(file_id: str, page: int, body: PageLayoutRequest):
        return analyze_pdf_page(file_id, page, body)

    @app.post('/v1/files/{file_id}/pages/{page}/ocr')
    def page_ocr(file_id: str, page: int, body: PageOcrRequest):
        return analyze_pdf_page(file_id, page, body, ocr=True)

    @app.get('/v1/capabilities')
    def capabilities():
        import importlib.metadata
        import shutil
        packages = {}
        for name in ('pymupdf', 'pillow', 'ocrmypdf', 'pymupdf4llm', 'pymupdf-fonts', 'pymupdfpro'):
            try:
                packages[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                packages[name] = None
        return {'packages': packages, 'tesseract': bool(shutil.which('tesseract')),
                'ghostscript': bool(shutil.which('gs')), 'readOperationsTriggerOcr': False}

    @app.post('/v1/files')
    def files_post(source: Source):
        return register(source)

    @app.get('/v1/files/{file_id}')
    def files_get(file_id: str):
        with app.state.cache.lease():
            r = app.state.cache.record(file_id)
            return {'id': file_id, 'sha256': r['sha256'], 'bytes': r['bytes'], **r['info']}

    @app.get('/v1/files/{file_id}/pages/{page}')
    def page_get(file_id: str, page: int, request: Request):
        return reply(file_id, 'page', request, page=page)

    @app.get('/v1/files/{file_id}/pages/{page}/image.{fmt}')
    def page_image(file_id: str, page: int, fmt: str, request: Request,
                   width: int = Query(1200, ge=1, le=16000), region: str = 'full'):
        return reply(file_id, 'render', request, f'image/{"jpeg" if fmt=="jpg" else fmt}', page=page,
                     format=fmt, quality='default', region=region, size=f'{width},')

    @app.get('/v1/files/{file_id}/pages/{page}/{kind}')
    def page_data(file_id: str, page: int, kind: str, request: Request, q: str = Query('', max_length=500)):
        if kind not in ('words', 'text', 'search', 'blocks'):
            raise HTTPException(404, 'Unknown page operation')
        if kind == 'search' and not q.strip():
            raise HTTPException(422, 'Search requires q')
        return reply(file_id, kind, request, page=page, **({'q': q} if kind == 'search' else {}))

    @app.get('/v1/files/{file_id}/toc')
    def toc(file_id: str, request: Request):
        return reply(file_id, 'toc', request)

    @app.get('/iiif/3/{file_id}~{page}/info.json')
    def iiif_info(file_id: str, page: int, request: Request):
        data, _ = operation(file_id, 'geometry', page=page)
        geometry = json.loads(data)
        return {'@context': 'http://iiif.io/api/image/3/context.json',
                'id': os.getenv('PDFTOOLS_PUBLIC_URL', str(request.base_url)).rstrip('/')+f'/iiif/3/{file_id}~{page}',
                'type': 'ImageService3', 'protocol': 'http://iiif.io/api/image', 'profile': 'level1',
                **geometry, 'maxArea': int(os.getenv('PDFTOOLS_MAX_PIXELS', '20000000')),
                'tiles': [{'width': 512, 'scaleFactors': [1,2,4,8,16,32,64,128]}],
                'extraFormats': ['png','webp'], 'extraQualities': ['gray'],
                'extraFeatures': ['regionSquare','regionByPct','sizeByWh','sizeByPct','sizeByConfinedWh']}

    @app.get('/iiif/3/{file_id}~{page}/{region}/{size}/{rotation}/{quality}.{fmt}')
    def iiif_image(file_id: str, page: int, region: str, size: str, rotation: str, quality: str, fmt: str, request: Request):
        if rotation != '0':
            raise HTTPException(422, 'Only rotation 0 is supported')
        return reply(file_id, 'render', request, f'image/{"jpeg" if fmt=="jpg" else fmt}',
                     page=page, region=region, units='px', size=size, format=fmt, quality=quality)

    @app.get('/iiif/3/{file_id}/manifest.json')
    def manifest(file_id: str, request: Request):
        info = files_get(file_id)
        base = os.getenv('PDFTOOLS_PUBLIC_URL', str(request.base_url)).rstrip('/')
        mid = f'{base}/iiif/3/{file_id}/manifest.json'
        items = []
        data, _ = operation(file_id, 'geometries')
        for page, geometry in enumerate(json.loads(data), 1):
            service = f'{base}/iiif/3/{file_id}~{page}'
            cid = f'{mid}/canvas/{page}'
            items.append({'id': cid, 'type': 'Canvas', 'label': {'none':[str(page)]}, **geometry,
                          'items':[{'id':cid+'/page','type':'AnnotationPage','items':[
                              {'id':cid+'/painting','type':'Annotation','motivation':'painting','target':cid,
                               'body':{'id':service+'/full/1000,/0/default.jpg','type':'Image','format':'image/jpeg',
                                       'service':[{'id':service,'type':'ImageService3','profile':'level1'}]}}]}]})
        return {'@context':'http://iiif.io/api/presentation/3/context.json','id':mid,'type':'Manifest',
                'label':{'none':[info['metadata'].get('title') or file_id]},'items':items}

    app.mount('/demo', StaticFiles(directory=Path(__file__).resolve().parent.parent/'demo', html=True), name='demo')
