import io
import json
from concurrent.futures import ThreadPoolExecutor

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import app
from pdf_tools.cache import Cache, Source


@pytest.fixture
def pdf_bytes():
    doc = pymupdf.open()
    for i in range(1001):
        page = doc.new_page(width=600, height=800)
        page.insert_text((50, 80), f'Archive page {i+1} Michurinka')
    return doc.tobytes()


@pytest.fixture
def client(tmp_path, monkeypatch, pdf_bytes):
    monkeypatch.setenv('CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(Cache, 'chunks', lambda self, source: iter([pdf_bytes]))
    with TestClient(app) as client:
        yield client


def register(client, **kw):
    response = client.post('/v1/files', json={'url': 'https://example.org/archive.pdf', **kw})
    assert response.status_code == 200, response.text
    return response.json()['id']


def test_thousand_pages_and_late_page(client):
    file_id = register(client)
    assert client.get(f'/v1/files/{file_id}').json()['pages'] == 1001
    base = f'/v1/files/{file_id}/pages/1000'
    words = client.get(base+'/words').json()['words']
    assert [w['text'] for w in words] == ['Archive', 'page', '1000', 'Michurinka']
    assert all(0 <= n <= 1 for n in words[0]['bboxNormalized'])
    assert len(client.get(base+'/search?q=Michurinka').json()['hits']) == 1
    image = client.get(base+'/image.png?width=300')
    assert image.status_code == 200, image.text
    assert Image.open(io.BytesIO(image.content)).size == (300, 400)
    assert client.get(base+'/image.png?width=300', headers={'If-None-Match': image.headers['etag']}).status_code == 304
    assert client.get(f'/v1/files/{file_id}/pages/1002').status_code == 404


def test_iiif(client):
    file_id = register(client)
    base = f'/iiif/3/{file_id}~1000'
    info = client.get(base+'/info.json').json()
    assert (info['width'], info['height']) == (2500, 3334)
    for region in ('full','square','0,0,500,600','pct:10,10,30,30'):
        for size in ('200,', ',200', '!200,200', '200,150', 'pct:10'):
            response = client.get(base+f'/{region}/{size}/0/gray.jpg')
            assert response.status_code == 200, response.text
            assert Image.open(io.BytesIO(response.content)).mode == 'L'
    assert client.get(base+'/full/16000,16000/0/default.jpg').status_code == 422
    assert client.get(base+'/full/nan,/0/default.jpg').status_code == 422
    assert client.get('/iiif/3/'+'a'*32+'~1/info.json').status_code == 404


def test_concurrent_registration_downloads_once(client, monkeypatch, pdf_bytes):
    calls = []
    def download(self, source):
        calls.append(source)
        yield pdf_bytes
    monkeypatch.setattr(Cache, 'chunks', download)
    with ThreadPoolExecutor(4) as pool:
        ids = list(pool.map(lambda _: register(client), range(4)))
    assert len(set(ids)) == 1
    assert len(calls) == 1


def test_refresh_signed_url_and_restart(client, monkeypatch, pdf_bytes):
    file_id = register(client, sourceId='nara:example:asset-1', revision='v1')
    response = client.post('/v1/files', json={'url':'https://example.org/archive.pdf?token=NEW',
                                           'sourceId':'nara:example:asset-1','revision':'v1'})
    assert response.json()['id'] == file_id
    cache = Cache()
    assert cache.record(file_id)['source']['url'].endswith('NEW')
    assert cache.record(file_id)['info']['pages'] == 1001
    # Eviction preserves identity; re-fetch validates the pinned checksum.
    with cache.lease():
        cache.reserve(cache.max_bytes)
    assert client.get(f'/v1/files/{file_id}/pages/1000/text').status_code == 200
    with cache.lease():
        cache.reserve(cache.max_bytes)
    monkeypatch.setattr(Cache, 'chunks', lambda self, source: iter([b'changed']))
    assert client.get(f'/v1/files/{file_id}/pages/1000/text').status_code == 409


def test_limits_and_failed_download_cleanup(client, monkeypatch):
    app.state.cache.max_source = 10
    assert client.post('/v1/files', json={'url':'https://example.org/a.pdf'}).status_code == 413
    assert not list(app.state.cache.root.rglob('*.part'))
    assert not list((app.state.cache.root/'bytes').glob('*.pdf'))


def test_legacy_reads_do_not_ocr(client, monkeypatch):
    def forbidden(*args):
        pytest.fail('Read operation invoked OCR')
    monkeypatch.setattr('app._ensure_ocr', forbidden)
    assert client.get('/thumbnail', params={'url':'https://example.org/a.pdf','page':1000}).status_code == 200
    assert client.get('/page-image', params={'url':'https://example.org/a.pdf','page':1002}).status_code == 404


def test_auth_and_source_validation(client, monkeypatch):
    assert client.post('/v1/files', json={'url':'file:///etc/passwd'}).status_code == 422
    assert client.post('/v1/files', json={'url':'https://example.org/a.pdf','sourceId':'x'}).status_code == 422
    monkeypatch.setenv('PDFTOOLS_TOKEN', 'secret')
    assert client.post('/v1/files', json={'url':'https://example.org/a.pdf'}).status_code == 401
    assert client.get('/health').status_code == 200
    assert client.post('/v1/files', json={'url':'https://example.org/a.pdf'},
                       headers={'Authorization':'Bearer secret'}).status_code == 200


def test_iiif_reads_are_public_but_writes_are_not(client, monkeypatch):
    # A viewer fetches info.json and tiles from the browser, so a token guarding
    # them would have to ship in the page. Reads are public; registration is not,
    # which is what keeps this service from being asked to fetch arbitrary URLs.
    file_id = client.post('/v1/files', json={'url':'https://example.org/a.pdf'}).json()['id']
    monkeypatch.setenv('PDFTOOLS_TOKEN', 'secret')

    assert client.get(f'/iiif/3/{file_id}~1/info.json').status_code == 200
    assert client.get(f'/iiif/3/{file_id}/manifest.json').status_code == 200
    assert client.post('/v1/files', json={'url':'https://example.org/a.pdf'}).status_code == 401
    assert client.get(f'/v1/files/{file_id}/pages/1').status_code == 401


def test_rejects_private_sources(tmp_path):
    from fastapi import HTTPException
    cache = Cache(tmp_path)
    with pytest.raises(HTTPException) as exc:
        cache.validate_url('http://127.0.0.1/test.pdf')
    assert exc.value.status_code == 403


def test_manifest_geometry_without_word_extraction(client):
    file_id = register(client)
    response = client.get(f'/iiif/3/{file_id}/manifest.json')
    assert response.status_code == 200
    manifest = response.json()
    assert manifest['type'] == 'Manifest'
    assert len(manifest['items']) == 1001
    assert manifest['items'][999]['width'] == 2500
    assert '~1000' in manifest['items'][999]['items'][0]['items'][0]['body']['service'][0]['id']


def test_corrupt_download_is_not_cached(client, monkeypatch):
    monkeypatch.setattr(Cache, 'chunks', lambda self, source: iter([b'not a PDF']))
    response = client.post('/v1/files', json={'url':'https://example.org/corrupt.pdf'})
    assert response.status_code == 422
    assert not list((app.state.cache.root/'bytes').glob('*.pdf'))


def test_byte_budget_and_partial_recovery(client):
    file_id = register(client)
    cache = app.state.cache
    partial = cache.root/'bytes'/'interrupted.part'
    partial.write_bytes(b'incomplete')
    with cache.lease():
        assert not partial.exists()
    source = cache.root/'bytes'/f'{file_id}.pdf'
    cache.max_bytes = source.stat().st_size + 100
    response = client.get(f'/v1/files/{file_id}/pages/1/image.png')
    assert response.status_code == 507
    assert sum(p.stat().st_size for p in (cache.root/'bytes').iterdir()) <= cache.max_bytes


def test_canonical_https_iiif_urls_behind_proxy(client, monkeypatch):
    monkeypatch.setenv('PDFTOOLS_PUBLIC_URL', 'https://pdf-tools.survos.com/')
    file_id = register(client)
    info = client.get(f'/iiif/3/{file_id}~1/info.json').json()
    assert info['id'] == f'https://pdf-tools.survos.com/iiif/3/{file_id}~1'
    manifest = client.get(f'/iiif/3/{file_id}/manifest.json').json()
    assert manifest['id'].startswith('https://pdf-tools.survos.com/')
    assert 'http://testserver' not in json.dumps(manifest)


def test_blocks_preserve_geometry_and_openapi(client):
    file_id=register(client)
    result=client.get(f'/v1/files/{file_id}/pages/1/blocks').json()
    assert result['blocks'][0]['text']=='Archive page 1 Michurinka'
    assert result['blocks'][0]['textSource']=='embedded-pdf'
    assert all(0<=v<=1 for v in result['blocks'][0]['bboxNormalized'])
    schema=client.get('/openapi.json').json()
    assert '/v1/analysis' in schema['paths']
    assert '/v1/files/{file_id}/pages/{page}/layout' in schema['paths']
    assert schema['paths']['/v1/analysis']['post']['requestBody']
