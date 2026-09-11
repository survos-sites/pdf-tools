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


def install(app: FastAPI):
    @asynccontextmanager
    async def lifespan(app):
        app.state.cache = Cache()
        # PyMuPDF must not run in the server's thread pool or share open Documents.
        with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
            app.state.pdf_pool = pool
            yield
    app.router.lifespan_context = lifespan
    app.add_middleware(CORSMiddleware, allow_origins=os.getenv('PDFTOOLS_CORS_ORIGINS', '*').split(','),
                       allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type'])

    @app.middleware('http')
    async def authentication(request, call_next):
        import secrets
        token = os.getenv('PDFTOOLS_TOKEN')
        if token and request.method != 'OPTIONS' and request.url.path not in ('/health', '/demo', '/demo/') and not request.url.path.startswith('/demo/'):
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
        headers = {'ETag': f'"{etag}"', 'Cache-Control': 'private, max-age=0, must-revalidate'}
        if request.headers.get('if-none-match') == headers['ETag']:
            return Response(status_code=304, headers=headers)
        return Response(data, media_type=media, headers=headers)

    app.state.register_pdf = register
    app.state.pdf_operation = operation

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
        if kind not in ('words', 'text', 'search'):
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
