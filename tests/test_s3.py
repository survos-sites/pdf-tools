import io

import boto3
from botocore.response import StreamingBody
from botocore.stub import Stubber

from pdf_tools.cache import Cache, Source


def test_s3_streams_selected_version(tmp_path, monkeypatch):
    monkeypatch.setenv('PDFTOOLS_S3_BUCKETS', 'rappnews')
    client = boto3.client('s3', region_name='us-east-1', aws_access_key_id='test', aws_secret_access_key='test')
    body = StreamingBody(io.BytesIO(b'%PDF-fixture'), 12)
    with Stubber(client) as stub:
        stub.add_response('get_object', {'Body': body}, {'Bucket':'rappnews', 'Key':'issue.pdf', 'VersionId':'v7'})
        monkeypatch.setattr(boto3, 'client', lambda *args, **kwargs: client)
        cache = Cache(tmp_path)
        source = Source(s3={'bucket':'rappnews','key':'issue.pdf','versionId':'v7'}, sourceId='rapp:issue', revision='7')
        with cache.lease():
            path, checksum = cache.acquire(source)
        assert path.read_bytes() == b'%PDF-fixture'
        assert len(checksum) == 64
        stub.assert_no_pending_responses()


def test_s3_bucket_allowlist(tmp_path, monkeypatch):
    import pytest
    from fastapi import HTTPException
    monkeypatch.setenv('PDFTOOLS_S3_BUCKETS', 'rappnews')
    cache = Cache(tmp_path)
    with cache.lease(), pytest.raises(HTTPException) as exc:
        cache.acquire(Source(s3={'bucket':'other','key':'issue.pdf'}))
    assert exc.value.status_code == 403
