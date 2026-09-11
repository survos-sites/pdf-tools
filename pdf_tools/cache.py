"""Disposable bytes, persistent source handles; callers hold the cache lease.

A single cross-process lock deliberately bounds downloads/rendering to one active
request per cache directory in this first local milestone. No eviction can race
an active reader. Symfony owns durable catalog state and re-registers on rebuild.
"""
import fcntl
import hashlib
import ipaddress
import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator


class S3Source(BaseModel):
    bucket: str = Field(min_length=1)
    key: str = Field(min_length=1)
    versionId: str | None = None


class Source(BaseModel):
    url: str | None = None
    s3: S3Source | None = None
    sourceId: str | None = Field(default=None, min_length=1, max_length=500)
    revision: str | None = Field(default=None, min_length=1, max_length=200)
    sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def validate_source(self):
        if (self.url is None) == (self.s3 is None):
            raise ValueError('Supply exactly one of url or s3')
        if (self.sourceId is None) != (self.revision is None):
            raise ValueError('sourceId and revision must be supplied together')
        if self.url and urlsplit(self.url).scheme not in ('http', 'https'):
            raise ValueError('Only HTTP(S) sources are supported')
        return self

    def identity(self):
        if self.sourceId:
            return [self.sourceId, self.revision]
        return self.s3.model_dump() if self.s3 else self.url


class Cache:
    def __init__(self, root=None, max_bytes=None, max_source=None):
        self.root = Path(root or os.getenv('CACHE_DIR', '.cache/pdf-tools')).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.max_bytes = max_bytes or int(os.getenv('PDFTOOLS_CACHE_BYTES', str(2 * 1024**3)))
        self.max_source = max_source or int(os.getenv('PDFTOOLS_MAX_SOURCE_BYTES', str(512 * 1024**2)))
        for name in ('sources', 'bytes'):
            (self.root / name).mkdir(exist_ok=True, mode=0o700)

    @contextmanager
    def lease(self):
        with (self.root / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                # Atomic writes from an interrupted process are never valid cache entries.
                for part in self.root.rglob('*.part'):
                    part.unlink(missing_ok=True)
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def handle(self, source):
        return hashlib.sha256(json.dumps(source.identity(), sort_keys=True).encode()).hexdigest()[:32]

    def record(self, file_id):
        if len(file_id) != 32 or any(c not in '0123456789abcdef' for c in file_id):
            raise HTTPException(404, 'Unknown file')
        path = self.root / 'sources' / f'{file_id}.json'
        if not path.exists():
            raise HTTPException(404, 'Unknown file; register its source first')
        return json.loads(path.read_text())

    def save(self, file_id, record):
        path = self.root / 'sources' / f'{file_id}.json'
        part = path.with_suffix('.part')
        part.write_text(json.dumps(record))
        part.chmod(0o600)
        part.replace(path)

    def reserve(self, size, keep=()):
        files = list((self.root / 'bytes').iterdir())
        used = sum(p.stat().st_size for p in files)
        for path in sorted(files, key=lambda p: p.stat().st_mtime):
            if used + size <= self.max_bytes:
                return
            if path.name in keep or path.suffix == '.part':
                continue
            used -= path.stat().st_size
            path.unlink()
        if used + size > self.max_bytes:
            raise HTTPException(507, 'Cache capacity exhausted; increase PDFTOOLS_CACHE_BYTES')

    def validate_url(self, url):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(400, 'Invalid HTTP source')
        allowed = os.getenv('PDFTOOLS_SOURCE_HOSTS', '').split(',')
        if allowed != [''] and parsed.hostname not in allowed:
            raise HTTPException(403, 'Source host is not allowed')
        if os.getenv('PDFTOOLS_ALLOW_PRIVATE_SOURCES') != '1':
            try:
                addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
            except OSError:
                raise HTTPException(400, 'Source DNS lookup failed')
            if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise HTTPException(403, 'Private source addresses are disabled')

    def chunks(self, source):
        if source.s3:
            import boto3
            allowed = os.getenv('PDFTOOLS_S3_BUCKETS', '').split(',')
            if source.s3.bucket not in allowed:
                raise HTTPException(403, 'S3 bucket is not configured in PDFTOOLS_S3_BUCKETS')
            client = boto3.client('s3', endpoint_url=os.getenv('S3_ENDPOINT'))
            args = {'Bucket': source.s3.bucket, 'Key': source.s3.key}
            if source.s3.versionId:
                args['VersionId'] = source.s3.versionId
            response = client.get_object(**args)
            try:
                yield from response['Body'].iter_chunks(chunk_size=1024 * 1024)
            finally:
                response['Body'].close()
            return
        url = source.url
        with httpx.Client(timeout=httpx.Timeout(120, connect=15)) as client:
            for _ in range(6):
                self.validate_url(url)
                with client.stream('GET', url) as response:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers['location']))
                        continue
                    response.raise_for_status()
                    if int(response.headers.get('content-length', '0')) > self.max_source:
                        raise HTTPException(413, 'Source exceeds size limit')
                    yield from response.iter_bytes(1024 * 1024)
                    return
            raise HTTPException(400, 'Too many source redirects')

    def acquire(self, source, expected=None):
        file_id = self.handle(source)
        dest = self.root / 'bytes' / f'{file_id}.pdf'
        if dest.exists():
            dest.touch()
            if expected is None:
                with dest.open('rb') as data:
                    expected = hashlib.file_digest(data, 'sha256').hexdigest()
            return dest, expected
        part = dest.with_suffix('.part')
        digest = hashlib.sha256()
        size = 0
        started = time.monotonic()
        try:
            with part.open('wb') as output:
                for chunk in self.chunks(source):
                    size += len(chunk)
                    if size > self.max_source or size > self.max_bytes:
                        raise HTTPException(413, 'Source exceeds size limit')
                    if time.monotonic() - started > 600:
                        raise HTTPException(504, 'Source download exceeded 600 seconds')
                    self.reserve(len(chunk), keep=(part.name,))
                    output.write(chunk)
                    output.flush()
                    digest.update(chunk)
            checksum = digest.hexdigest()
            if (expected and checksum != expected) or (source.sha256 and checksum != source.sha256):
                raise HTTPException(409, 'Source bytes changed; register a new revision')
            part.replace(dest)
            return dest, checksum
        except HTTPException:
            raise
        except Exception:
            # Never expose signed URLs or credentials in errors.
            raise HTTPException(502, 'Source download failed; check source access or refresh its signed URL')
        finally:
            part.unlink(missing_ok=True)
