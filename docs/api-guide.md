# API integration guide

This documents the implemented service, not a future OpenAI-compatible facade.
Interactive schemas: `/docs`. Machine-readable schema: `/openapi.json`.

## Authentication and errors

Set `PDFTOOLS_TOKEN` on the service and send `Authorization: Bearer <token>` for
API/IIIF calls. Without it the local service has no authentication. Health and demo
assets remain public; the demo can accept a token without saving it to storage.
Registered file IDs are references, not authorization credentials.

Errors currently use FastAPI's `{"detail": ...}` envelope. Validation errors may
contain a list of field errors. Do not assume an OpenAI error envelope.

| HTTP status | Meaning / caller action |
|---|---|
| 401 | Configure the bearer token |
| 403 | Source host/private address/S3 bucket is disallowed |
| 404 | Unknown handle or out-of-range page; re-register a lost handle |
| 409 | Checksum/revision conflict; provide a new revision |
| 413 | Source exceeds configured byte limit |
| 422 | Invalid input, corrupt PDF, unsupported operation/geometry |
| 502 | Source fetch failed; inspect access or renew its URL |
| 503 | Optional legacy OCR dependencies missing |
| 504 | Streamed download exceeded its time budget |
| 507 | Cache cannot accommodate the source plus requested artifact |

## Register a source

```bash
curl -sS http://127.0.0.1:5001/v1/files \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.org/issue.pdf","sourceId":"archive:issue:asset-1","revision":"v1"}'
```

Illustrative response (IDs and byte counts vary):

```json
{
  "id": "0123456789abcdef0123456789abcdef",
  "sha256": "<64 lowercase hex characters>",
  "bytes": 123456,
  "pages": 83,
  "metadata": {"title": "Example issue"},
  "iaIdentifier": null
}
```

Supply `sourceId` and `revision` together. Without them the URL or S3 reference
becomes the identity input. Optional `sha256` asserts the expected content. URLs
must use HTTP(S); local filesystem paths are not accepted.

For S3, replace `url` with:

```json
{"s3":{"bucket":"rappnews","key":"issues/issue.pdf","versionId":"optional-version"},"sourceId":"rappnews:issue:asset-1","revision":"v1"}
```

Credentials and S3 endpoint configuration belong to the server environment.
`PDFTOOLS_S3_BUCKETS` must allow the bucket. Standard boto3 credentials/profiles
are used. S3 output uploads are not implemented. Version IDs and document revision
labels have different roles: the former selects the object version, the latter
is the caller's stable revision identity.

## Read a selected page

Using the returned ID in place of FILE_ID:

```text
GET /v1/files/FILE_ID
GET /v1/files/FILE_ID/pages/64
GET /v1/files/FILE_ID/pages/64/text
GET /v1/files/FILE_ID/pages/64/words
GET /v1/files/FILE_ID/pages/64/search?q=Michurinka
GET /v1/files/FILE_ID/pages/64/image.png?width=1200
GET /v1/files/FILE_ID/pages/64/image.jpg?width=800&region=100,200,300,400
GET /v1/files/FILE_ID/toc
```

Text is `{"page":64,"text":"..."}`. Words have `text`, `block`, `line`, `n`,
`bboxPt` and `bboxNormalized`; search has `page` and a `hits` list with those box
representations. Empty text is a valid result for a scanned/photo page and never
triggers automatic OCR. Page info includes point/pixel size, rotation, word count,
and whether extractable words exist.

Images support PNG, JPEG (`jpg`) and WebP. Width is bounded; total pixels and
maximum dimension are separately checked. Regions use x,y,width,height in PDF
points, or `pct:x,y,w,h`. Returned image bytes are suitable for streaming to disk.
Responses support ETag conditional requests with 304. Cache policy is currently
private and requires revalidation; do not infer immutable public CDN semantics.

## IIIF and viewers

```text
GET /iiif/3/FILE_ID~64/info.json
GET /iiif/3/FILE_ID~64/full/800,/0/default.jpg
GET /iiif/3/FILE_ID~64/pct:10,20,30,40/600,/0/gray.png
GET /iiif/3/FILE_ID/manifest.json
```

Supported regions: full, square, pixel rectangle, percent rectangle. Sizes: max,
width-only, height-only, explicit width/height, confined width/height, percentage.
Only rotation 0 is supported. Quality is default or gray. ImageService3 declares
level1, with extra supported features; external conformance certification has not
been performed. A manifest provides one Canvas per PDF page.

Use `/demo/` for the working OpenSeadragon reader. It includes all eight benchmark
sources, downloads them only when selected, and exposes text, word export and
search overlays. Diva.js integration is a separate future comparison. The demo
currently downloads OpenSeadragon from a pinned CDN URL.

## Harvest

Start the Python service with `./run.sh`, then run from Harvest:

```bash
php bin/console pdf:inspect 'https://example.org/issue.pdf' \
  --source-id=archive:issue:asset-1 --revision=v1 --page=64 --query=Michurinka
```

The client defaults to `http://127.0.0.1:5001`; override `PDFTOOLS_URL` and optional
`PDFTOOLS_TOKEN`. The command writes document/page JSON and PNG into
`var/pdf-tools/{fileId}` and prints the manifest URL. `--output` changes the parent
directory. `--version-id` selects an S3 object version. The PNG write is streamed
and atomically replaces its destination only after success.

`App\Service\PdfToolsClient` is injectable elsewhere. The command is currently the
explicit end-to-end integration; no automatic normalization or Messenger dispatch
was added. Existing `PdfMeta` and Internet Archive processing remain intact.
