# Production

PDF Tools is deployed at https://pdf-tools.survos.com with bearer authentication.
See [production configuration, validation and updates](docs/production.md).

# PDF Tools

Local PDF inspection, text/word extraction, page images and IIIF for Harvest.
The repository, local checkout, and deployed app are named `pdf-tools`. It began
as `pdf-to-ocr`; existing OCR/materialization routes are retained alongside the
PyMuPDF read and rendering API. See the production guide above for the live service.

## Detailed documentation

- [Architecture and ownership](docs/architecture.md): identity, revisions, cache lifecycle, concurrency and recovery.
- [API integration guide](docs/api-guide.md): HTTP/S3 registration, page operations, errors, coordinates, IIIF and Harvest.
- [Release readiness](docs/release-readiness.md): dependency audit, recommended GitHub Actions and remaining Dokku work.
- [Symfony packaging and API discussion](docs/symfony-api-design.md): existing ai-workflow integration, proposed PDF client/bundle and precise OpenAI compatibility boundaries.
- [Recorded validation](docs/validation-2026-09-11.md): real archive and eight-document benchmark results.

## Start and use from Harvest

Python 3.12 or newer:

```bash
./run.sh                     # http://127.0.0.1:5001
# Or, with dependencies already installed:
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 5001
```

The read API requires neither Tesseract nor Ghostscript. `run.sh` installs
`requirements-read.txt`; install `requirements.txt` for the legacy OCR routes.
The demo is at http://127.0.0.1:5001/demo/ and OpenAPI is at `/docs`.
The demo uses OpenSeadragon (pinned CDN dependency), with page navigation,
existing text, search overlays, word JSON export and a IIIF manifest export.
Diva.js can consume the same manifest in a later viewer comparison; it is not integrated yet.

In `~/sites/harvest`:

```bash
php bin/console pdf:inspect \
  'https://www.marxists.org/history/ussr/culture/soviet-life/full-issues/1961/sim_soviet-life_1961-02_2.pdf' \
  --page=64 --query=Michurinka

php bin/console pdf:inspect 's3://rappnews/path/issue.pdf' \
  --source-id=rappnews:issue:asset-1 --revision=2026-09 --page=850
```

`PDFTOOLS_URL` defaults to `http://127.0.0.1:5001` in Harvest. `PDFTOOLS_TOKEN`
is optional and must match the Python service when set. Outputs go to
`var/pdf-tools/{fileId}/`: document info, page info, text, words, optional search
hits, and PNG. This explicit command does not change normalization or trigger paid
OCR. The existing cheap `PdfMeta` HTTP-range probe remains intact.

## Responsibilities

Symfony owns catalog identities/provenance, source revisions, Messenger queues,
retries, retention and durable S3 outputs. Python owns PDF operations, streaming
source access and a disposable local cache. There is no second durable job queue.
`PdfToolsClient` is the reusable integration boundary in Harvest.

## Source contract

```json
{"url":"https://example.org/issue.pdf","sourceId":"rappnews:issue:asset-1","revision":"v1"}
```

Or direct S3 (using server-side credentials, not credentials in the payload):

```json
{"s3":{"bucket":"rappnews","key":"path/issue.pdf","versionId":"optional-object-version"},"sourceId":"rappnews:issue:asset-1","revision":"v1"}
```

POST these to `/v1/files`. Supply exactly one of `url` or `s3`. `sourceId` and
`revision` must be provided together. `sha256` may optionally assert the expected
content checksum. The response includes `id`, `sha256`, `bytes`, `pages`, PDF
`metadata` and `iaIdentifier` when present. Registration does not scan page text.

IDs are 32 hexadecimal characters derived from the explicit identity + revision,
or the S3 reference / URL when no identity is supplied. Always provide identity
and revision for presigned URLs: refreshing credentials then preserves the handle.
Re-register the same identity to update an expired download URL. Credential-bearing
URLs are stored only in private local source records, not returned by the API.

A handle pins the first validated content checksum. Cached reads use those bytes.
After eviction, a changed source returns **409**, never silently substitutes a new
PDF under existing derived URLs. Register a new revision for changed content.
Automatic ETag/Last-Modified revalidation is deliberately deferred: Symfony owns
revision discovery for this milestone. A URL-only handle must likewise be replaced
with an explicit revision when its content changes.

## Read API

All public page numbers are **1-based**; PyMuPDF indexes are 0-based internally.
Boxes use `[x0,y0,x1,y1]` in displayed PDF points and normalized page coordinates.
The image crop `region` uses `x,y,width,height`, a different representation.

| Route | Result |
|---|---|
| `GET /v1/capabilities` | Installed core/optional packages and OCR executables |
| `POST /v1/files` | Register/fetch HTTP or S3 source |
| `GET /v1/files/{id}` | Cached document metadata |
| `GET /v1/files/{id}/pages/{page}` | Size in points/pixels, rotation, word count, text-layer flag |
| `GET /v1/files/{id}/pages/{page}/text` | Existing page text |
| `GET /v1/files/{id}/pages/{page}/words` | Words with point and normalized boxes |
| `GET /v1/files/{id}/pages/{page}/search?q=…` | Hit rectangles |
| `GET /v1/files/{id}/pages/{page}/image.png?width=1200&region=full` | Page/crop; also jpg/webp |
| `GET /v1/files/{id}/toc` | Existing PDF bookmarks |
| `GET /iiif/3/{id}~{page}/info.json` | IIIF Image API 3 service description |
| `GET /iiif/3/{id}~{page}/{region}/{size}/0/{quality}.{format}` | IIIF region rendering |
| `GET /iiif/3/{id}/manifest.json` | Presentation 3 manifest, one Canvas per page |

Regions: `full`, `square`, `x,y,w,h`, `pct:x,y,w,h`. IIIF numeric regions are in
canvas pixels. Sizes: `max`, `w,`, `,h`, `w,h`, `!w,h`, `pct:n`. Only rotation `0`;
qualities `default` and `gray`; formats jpg/png/webp. Pixel limits still apply to
`max`. Canvas geometry uses configurable 300 DPI, including for embedded scans;
native embedded-image DPI detection is deferred. The facade advertises level1;
it is exercised with OpenSeadragon but not externally conformance-certified.

OpenSeadragon setup:

```js
OpenSeadragon({id: 'viewer', tileSources: '/iiif/3/FILE_ID~64/info.json'});
```

For an authenticated service, provide `ajaxHeaders: {Authorization: 'Bearer …'}`
and `loadTilesWithAjax: true`. Do not put bearer tokens in URLs. The demo accepts
an in-memory token; it is not saved in browser storage.

## Local cache and concurrency

Sources stream into `.part` files with incremental size checks and SHA-256.
Successful files are renamed atomically; abandoned partial files are removed on
the next cache lease. Restarts reuse complete downloads and derivatives. Interrupted
downloads restart from byte zero; HTTP Range resume is not yet implemented.

The byte cache covers source PDFs and JSON/image derivatives, with least-recently-used
mtime eviction. Source handle records survive byte eviction; Symfony can re-register
if the entire cache is discarded. Derived artifacts use the content checksum,
operation version and parameters, so two revisions cannot collide. A derivative hit
can be served even if source bytes have been evicted. Responses have content ETags
and conservative `private, max-age=0, must-revalidate` headers. Immutable public CDN
URLs, HMAC read URLs and S3 derivative write-through are future work.

**Initial throughput limit:** a cross-process cache lease serializes downloads and
cache-miss processing across this cache directory. It protects active files from
eviction and prevents duplicate concurrent downloads. PyMuPDF runs in one spawned
process, not FastAPI's thread pool. Documents are opened per operation; no unsafe
shared document LRU. A manifest scans page geometry once, without text extraction.
This prioritizes a correct local integration over tile throughput during large
new downloads. Separate per-source leases, process resource limits and cancellation
are needed before production/large parallel ingest. Output pixel limits do not
bound every internal allocation of a complex PDF.

## Configuration

| Variable | Default / meaning |
|---|---|
| `PORT` | `5001` in local run.sh; Docker remains configurable |
| `CACHE_DIR` | `.cache/pdf-tools` (persistent, private local directory) |
| `PDFTOOLS_CACHE_BYTES` | 2 GiB total source/derivative byte budget |
| `PDFTOOLS_MAX_SOURCE_BYTES` | 512 MiB per source |
| `PDFTOOLS_MAX_PIXELS` | 20,000,000 pixels per image; max dimension 16,000 |
| `PDFTOOLS_NATIVE_DPI` | 300 for IIIF canvas space |
| `PDFTOOLS_TOKEN` | Optional bearer token for API and IIIF; unset for loopback demo |
| `PDFTOOLS_CORS_ORIGINS` | `*`; comma-separated origins |
| `PDFTOOLS_SOURCE_HOSTS` | Optional comma-separated HTTP source host allowlist |
| `PDFTOOLS_ALLOW_PRIVATE_SOURCES` | Off; `1` only for local fixtures/internal trusted sources |
| `PDFTOOLS_S3_BUCKETS` | Required comma-separated allowed S3 buckets |
| `S3_ENDPOINT` | Optional S3-compatible endpoint; omitted for AWS |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_DEFAULT_REGION` | Standard boto3 credential/config chain |

HTTP redirects are checked and private destination addresses rejected by default.
The DNS check is not a replacement for outbound network isolation against rebinding.
Keep the initial service on loopback/trusted networks. For private S3 collections,
configure a token before sharing service access; registered IDs are not credentials.
Source records and legacy OCR output are outside the disposable byte budget.
Legacy OCR routes retain their prior synchronous behavior and independent cache.

## Optional engines

[Upstream optional extras](https://github.com/pymupdf/PyMuPDF#optional-extras):

- `pymupdf4llm`: structured Markdown/JSON for RAG; evaluate on periodical reading order.
- `pymupdf-fonts`: extended fonts for future inserted text / multilingual output.
- `pymupdfpro`: Office input support, outside this PDF milestone; requires its own licensing setup.
- Tesseract: already installed locally; used explicitly for OCR, never on read requests.

PyMuPDF's upstream license is AGPL-3.0, with commercial licensing available from
Artifex. No repository license has been added or changed. A public repository alone
should not be treated as a complete license-compliance determination.

## Tests and benchmark documents

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/benchmark.py   # opt-in ~182 MB downloads via running API
```

The offline suite generates a 1,001-page PDF and checks page 1,000, search/geometry,
IIIF crops, concurrency, eviction/refetch, changed content, size limits, partial
cleanup, invalid sources and S3 version selection (botocore stub, no cloud account).
`demo/fixtures.json` records all eight files from the
[PyMuPDF benchmark reference](https://pymupdf.readthedocs.io/en/latest/app4.html#appendix4-files-used).
The accessible download location is a community mirror, explicitly identified in
that manifest; PDFs are not redistributed in this repository. The script checks
sizes and records downloaded checksums, page counts, last-page words and two render
timings in ignored `work/benchmark.json`. Network fixtures are opt-in, not required
for offline tests. RappNews S3 end-to-end validation awaits the incoming bucket.

## Next milestones

- Wire `PdfToolsClient` into the selected Harvest/Messenger acquisition workflow.
- S3 write outputs, page-range jobs, progress/recovery, bookmarks and text-layer jobs.
- HMAC/public cache contracts and concurrent download/render leases.
- Viewer comparison with Diva.js; registered-source management and expiry.

---

## Legacy OCR service reference

# PDF-to-OCR Microservice

A FastAPI service that accepts a PDF URL, runs OCRmyPDF with Tesseract, and
provides searchable PDFs, extracted text, page images, and thumbnails. It also
supports materializing an ordered list of JPG scans into a searchable PDF/A.

## Endpoints

| Endpoint | Returns | Use case |
|---|---|---|
| `GET /ocr?url=...` | Searchable PDF | Store the OCR'd PDF back to S3 |
| `POST /materialize` | Searchable PDF/A bytes | Build a PDF/A from ordered JPG URLs |
| `GET /text?url=...` | JSON per-page text | Index into Meilisearch |
| `GET /page-image?url=...&page=1&dpi=200` | PNG image | On-demand full-res page view |
| `GET /thumbnail?url=...&page=1` | PNG thumbnail (72 DPI) | Browse/preview UI |

All endpoints accept a `url` parameter pointing to a PDF (e.g. an S3
presigned URL). Read endpoints use the source PDF directly and never trigger OCR.
Only `/ocr` invokes OCR and caches its result.

`POST /materialize` is different: it accepts a JSON payload with an ordered
list of JPG URLs, downloads them into a temporary working directory, assembles
them losslessly with `img2pdf`, then runs OCRmyPDF to emit a searchable
`PDF/A-2` document.

## OCR Engine Notes

`ocrmypdf` is the pipeline coordinator, not the OCR engine itself.

- OCR engine: `Tesseract`
- PDF/image rasterizer in OCRmyPDF 17.x: `pypdfium2` by default
- Page cleanup for `clean_final=True`: `unpaper`
- PDF assembly and metadata handling: `pikepdf`

For `POST /materialize`, the expensive step is still Tesseract OCR. Downloading
JPGs from colocated object storage should usually be fast; OCR and PDF/A
conversion dominate latency on larger jobs.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OCR_LANGUAGE` | `eng` | Tesseract language(s), e.g. `eng+spa` |
| `PORT` | `5000` | Set automatically by Dokku |

## Deploy to Dokku

Use the [production deployment guide](docs/production.md) for the existing
`pdf-tools` app on fsn1. The examples below document the retained legacy API;
production requests require `Authorization: Bearer $PDFTOOLS_TOKEN`.

## Usage Examples

```bash
# Get a searchable PDF back
curl -o result.pdf "https://pdf-tools.survos.com/ocr?url=https://example.com/scan.pdf"

# Build a searchable PDF/A from ordered JPG scans
curl \
  -X POST "https://pdf-tools.survos.com/materialize" \
  -H "Content-Type: application/json" \
  -o materialized.pdf \
  -d '{
    "image_urls": [
      "https://example.com/page-0001.jpg",
      "https://example.com/page-0002.jpg"
    ],
    "title": "Example scan",
    "author": "Survos",
    "keywords": "scan,materialized",
    "language": "eng"
  }'

# Get extracted text as JSON (for Meilisearch indexing)
curl "https://pdf-tools.survos.com/text?url=https://example.com/scan.pdf"

# Get page 3 as a high-res PNG
curl -o page3.png "https://pdf-tools.survos.com/page-image?url=https://example.com/scan.pdf&page=3&dpi=300"

# Get a thumbnail of the first page
curl -o thumb.png "https://pdf-tools.survos.com/thumbnail?url=https://example.com/scan.pdf"
```

## Response format for /text

```json
{
  "url": "https://example.com/scan.pdf",
  "page_count": 3,
  "pages": [
    {"page": 1, "text": "First page content..."},
    {"page": 2, "text": "Second page content..."},
    {"page": 3, "text": "Third page content..."}
  ]
}
```

## Request Format for /materialize

```json
{
  "image_urls": [
    "https://example.com/page-0001.jpg",
    "https://example.com/page-0002.jpg"
  ],
  "title": "Example scan",
  "author": "Survos",
  "keywords": "archive,scan",
  "language": "eng"
}
```

Field notes:

- `image_urls` is required and order-sensitive.
- Images are downloaded as `page_0000.jpg`, `page_0001.jpg`, and so on.
- `language` defaults to `OCR_LANGUAGE` or `eng`.
- `title`, `author`, and `keywords` are written into the output PDF metadata.

## PDF/A and Metadata

The materialized output is written as `PDF/A-2`, which is an archival subset of
PDF intended for long-term preservation. In practice that means the file is
self-contained and avoids fragile features that make future rendering less
reliable.

Metadata is carried into the output document through OCRmyPDF. The current
endpoint supports:

- `title`
- `author`
- `keywords`

These fields improve indexing, recordkeeping, and downstream archival workflows.
`language` affects OCR behavior and may inform document language tagging, but it
is not the same as descriptive metadata like title or author.

## Performance Notes

Current behavior is synchronous and blocking per request.

- Downloading JPGs from Hetzner object storage should be relatively fast when
  the service and bucket are colocated.
- `img2pdf` preserves the original JPEG data losslessly and is usually fast.
- Tesseract OCR is the main latency source.
- Returning a large PDF over HTTP is acceptable for now, but storing the result
  in object storage and returning a URL is a better fit for larger jobs.

For current expected volume, Dokku timeouts of `300s` are acceptable. If scan
materialization becomes large or frequent, move to an S3-backed output flow.

## ScanStationAI Workflow

1. **Appliance** scans documents → uploads raw PDF to S3
2. **Symfony** calls `/ocr?url=s3-presigned-url` → stores searchable PDF back to S3
3. **Symfony** calls `/text?url=s3-url-of-ocr-pdf` → indexes per-page text in Meilisearch
4. **UI** calls `/thumbnail` and `/page-image` on demand when user browses documents

No need to pre-split PDFs into individual images — pages are rendered on
the fly when requested.

## Local Development

```bash
pip install -r requirements.txt
# Needs tesseract and ghostscript installed:
# macOS: brew install tesseract ghostscript
# Ubuntu: apt install tesseract-ocr ghostscript
uvicorn app:app --reload --port 5000
```

## Future Enhancements

- Accept `image_urls` plus precomputed OCR text in JSON so this service can
  skip Tesseract for scan materialization
- Store materialized PDF/A back to S3 automatically and return a URL/object key
- Return a task ID for async processing (Redis + Celery or Symfony Messenger)
- Accept S3 paths directly instead of URLs
- Store OCR'd PDFs back to S3 automatically
- Webhook callback when OCR is complete

## Future Request Shape for Precomputed OCR

When scan OCR is produced upstream, the better contract is likely a second
materialization payload that carries both ordered JPG URLs and ordered OCR text.
That would move OCR outside this request path and make real-time materialization
much more plausible.

Example shape:

```json
{
  "pages": [
    {
      "image_url": "https://example.com/page-0001.jpg",
      "ocr_text": "First page text"
    },
    {
      "image_url": "https://example.com/page-0002.jpg",
      "ocr_text": "Second page text"
    }
  ],
  "title": "Example scan",
  "author": "Survos",
  "keywords": "archive,scan",
  "language": "eng"
}
```

That path would require a different implementation than `ocrmypdf.ocr()`,
because OCRmyPDF expects to run OCR itself rather than consume precomputed text.
