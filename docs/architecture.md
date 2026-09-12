# Architecture and ownership

Status: implemented local read milestone, 2026-09-11. Proposed extensions are
explicitly identified. The Python repository, checkout and Dokku app are named `pdf-tools`.
It began as `pdf-to-ocr` and grew to include the PyMuPDF read API.

## Intended consumers

Harvest resolves catalog records into assets and calls PDF Tools for selected-page
operations. RappNews from the Library of Virginia is the upcoming S3 integration.
NARA records and Library of Virginia cases can contain multiple PDFs or ordered
page images. Identity belongs to the individual asset within a record; a catalog
record ID alone is insufficient when the record has several files.

PDF Tools does not discover NARA records, crawl archive websites, classify article
boundaries or decide which OCR provider to pay. Existing Internet Archive images
and text should continue to be reused when available. Its IIIF services need not
be replaced by re-rendering the same sources locally.

## Ownership table

| Concern | Authority | Current implementation |
|---|---|---|
| Catalog identity, provenance, asset ordering | Symfony/Harvest | Existing provider and dataset code |
| Source revision discovery | Symfony | Client accepts explicit sourceId/revision |
| Queue, retries, workflow and claims | Symfony | Existing infrastructure; PDF jobs not wired yet |
| Durable original and result storage | S3/owning application | Python supports S3 source reads only |
| Fetching a selected source | Python | HTTP or configured S3, streamed to disk |
| PDF interpretation | Python worker process | PyMuPDF; selected page operations |
| Disposable source/derivative bytes | Python | Bounded local filesystem cache |
| Viewer and coordinate conversion | Python IIIF + browser | OpenSeadragon demo |
| Whole-document OCR/materialization | Legacy Python endpoints | Optional dependencies, synchronous |

## Request lifecycle

1. Symfony supplies an HTTP URL or an S3 reference, optionally with stable asset
   identity and an explicit revision. Presigned URLs should always carry identity.
2. Python hashes the identity into a local handle. Handle records retain access
   details separately from the public metadata response.
3. A cache lease prevents concurrent downloads and eviction of files in use.
4. Missing bytes stream to a temporary file. Size limits and SHA-256 are checked.
   The completed file is atomically renamed and validated as a nonempty,
   unencrypted PDF before first registration succeeds.
5. Basic registration reads document metadata and page count, without scanning
   every page for text. Page inspection is a separate operation.
6. The worker opens the PDF for the requested operation and closes it afterwards.
7. JSON/images are cached under a hash of content checksum, operation version and
   parameters. ETags describe returned bytes.

On a derivative hit the source need not be present. On a source miss the saved
access reference is used again; changed bytes return 409 against a pinned revision.
Refreshing an expired presigned URL through registration preserves the handle when
sourceId and revision remain the same. Clients must provide a new revision for a
new document version.

## Persistence and deletion semantics

`CACHE_DIR/sources` contains private source records and is outside the disposable
byte quota. `CACHE_DIR/bytes` contains source PDFs and derivatives and is evictable.
The catalog of record remains in Symfony: losing the complete Python cache is
recoverable by registration. Do not make a permanent partner deliverable exist only
inside this cache.

Automatic source freshness checks, source deletion/list APIs and record expiry
are not implemented. No public delete endpoint means no current API promise about
cascading deletion of derivatives. A future implementation should remove access
handles independently of content shared by multiple handles.

`legacy-ocr` retains the old separate OCR cache and is outside the new byte budget.
It must not be mistaken for durable output storage or a bounded production cache.

## Concurrency and recovery

The first implementation serializes leased operations across one cache directory.
This is intentionally simple: no duplicate downloads, no eviction of an active
source, and no shared PyMuPDF Document accessed by concurrent threads. PDF work runs
in one spawned process. This protects correctness but a large download delays
other requests needing the lease. More Uvicorn workers do not remove that shared
cache bottleneck.

An interrupted download leaves a `.part` file; the next lease removes it and the
next fetch starts from zero. Completed files and records survive service restart.
There is no HTTP Range resume, durable Python job registry, worker cancellation or
per-process memory limit in this milestone. An output pixel cap does not guarantee
a maximum memory allocation while decoding complex PDF content.

Before concurrent archive ingest, replace the global lease with per-source leases
and coordinated capacity reservations, introduce bounded process workers and
explicit cancellation/timeouts, and test crashes during each state transition.
Keep Messenger the durable scheduler throughout that change.

## Coordinates

API pages are 1-based. PyMuPDF indexes and some upstream archive canvas indexes
are 0-based: perform that conversion once at an integration boundary.

Words/search return `bboxPt` and `bboxNormalized`, both `[x0,y0,x1,y1]`, in displayed
page orientation. Image regions are `[x,y,width,height]`. Ordinary API image crops
use PDF points; IIIF numeric regions use canvas pixels. The current IIIF canvas
uses configured DPI, default 300, rather than native embedded-image resolution.
Normalized boxes are the safest way to map highlights to that canvas.

The manifest reads geometry for every page but does not extract every page's text.
The legacy `/text` endpoint necessarily returns all pages; new callers should use
the selected-page endpoint for large sources.
