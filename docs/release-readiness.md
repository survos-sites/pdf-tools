# Dependencies, CI and Dokku readiness

Assessment date: 2026-09-11. Publishing source to GitHub is appropriate; public
production deployment has outstanding work. This document does not record a
completed dependency upgrade, container build or deployment.

## Dependency audit

The installed read environment is internally consistent (`pip check` passed).
Current releases were checked against PyPI, npm and Tesseract's upstream releases.

| Dependency | Installed/pinned | Latest observed | Required action |
|---|---|---|---|
| FastAPI | 0.115.6 | 0.141.1 | Upgrade and retest request/response behavior |
| Uvicorn | 0.34.0 | 0.52.4 | Upgrade and retest startup/shutdown |
| Starlette | 0.41.3 | 1.6.0 | Resolve with FastAPI, test middleware/streaming |
| OpenSeadragon | 5.0.1 | 6.1.1 | Upgrade both script and image paths, viewer QA |
| PyMuPDF | 1.28.2 | 1.28.2 | Current locally |
| HTTPX | 0.28.1 | 0.28.1 | Current locally |
| boto3 | 1.43.92 | 1.43.92 | Current locally |
| Pillow | 12.3.0 locally; 11.1.0 full requirements | 12.3.0 | Remove conflicting older production pin |
| pytest | 9.1.1 | 9.1.1 | Current locally |
| Tesseract | 5.5.3 locally | 5.5.3 | Confirm container's distro build separately |
| OCRmyPDF | >=17.4; absent locally | 17.11.0 | Install and exercise full OCR path |
| pikepdf | >=10,<11; absent locally | 10.13.0.post1 | Validate full environment |
| img2pdf | >=0.5; absent locally | 0.6.3 | Validate materialization |
| NumPy | 2.2.3 full pin | 2.5.3 | Audit need; no direct use in current service |
| OpenCV headless | 4.11.0.86 full pin | 5.0.0.93 | Audit need; major upgrade if retained |
| pytesseract | 0.3.13 full pin | 0.3.13 | Audit need; no direct use in current service |

Consolidate shared requirements so full and read-only installations agree. Lock a
resolved/tested environment for deployment. Removing a direct dependency does not
mean it disappears if OCRmyPDF needs it transitively. Do not upgrade major packages
solely to eliminate an outdated report without compatibility testing.

Optional PyMuPDF4LLM, extra fonts and Pro remain optional. `/v1/capabilities`
reports installed versions and executable presence. The current read environment
has Tesseract but lacks OCRmyPDF/Ghostscript; read tests do not certify OCR output.

## Recommended GitHub Actions (not installed in this milestone)

1. PR/push checks: install read/dev dependencies on Linux/Python 3.12, run offline
   pytest, validate JavaScript syntax, and check dependency consistency.
2. Container check: build the Dockerfile with full dependencies; start it and
   exercise health, generated PDF registration/rendering and OCR/materialization
   using tiny generated scans. Merely building the image is insufficient.
3. Dependency maintenance: automated update PRs plus a vulnerability audit. Keep
   runtime and test requirements coordinated; review OpenSeadragon upgrades.
4. Manual network benchmark: run the eight checksum-pinned fixtures on demand or
   on a modest schedule. Record timings/artifacts; external PDF hosts must not make
   every PR flaky. Use no private bucket credentials for public fork PRs.
5. Later release workflow: publish a tested container artifact, then explicitly
   deploy that immutable version. Keep deploy secrets outside ordinary PR jobs.

There is currently no Actions workflow or automatic Dokku deployment configured
by this work. Adding CI and dependency upgrades are the next release tasks.

## Before Dokku

- Validate a complete Docker build and both read and legacy OCR paths.
- Mount a persistent private cache volume and set CACHE_DIR to that mount. Size
  the disk budget, temporary working space and container memory together.
- Configure bearer authentication, source/bucket allowlists, S3 access and CORS
  for the intended consumers. The current DNS check alone does not prevent DNS
  rebinding; enforce outbound network policy for untrusted URL registration.
- Decide whether the demo and IIIF will be private. A registered handle is not an
  access token; the current token applies service-wide, without tenant isolation.
- Set proxy/download timeouts deliberately. Registration can fetch hundreds of MB;
  the global cache lease serializes work. Long acquisition should eventually be
  driven by Symfony jobs rather than a browser request.
- Define worker memory/CPU limits and crash recovery. Pixel limits only constrain
  output dimensions; legacy caches are outside the new byte budget.
- Confirm readiness/health checks, application port, domain, HTTPS and rollback
  with the actual Dokku host. None of those host settings has been verified here.
- Keep S3 originals and generated partner deliverables under explicit durable
  retention. Do not depend on an evictable local cache for the only copy.

The repository name, GitHub remote and Dokku app name need not change together.
Any service rename needs a caller/domain/config migration; no rename was performed.

## Validation already available

See [the recorded results](validation-2026-09-11.md): 13 offline Python tests,
one opt-in Soviet Life test, two PHP client tests, all eight real benchmark PDFs,
manual OpenSeadragon page/search checks, restart reuse, and Harvest page 3,000.
The S3 test uses a stubbed client. Actual RappNews S3 validation awaits access.

References: [FastAPI releases](https://pypi.org/project/fastapi/),
[Uvicorn releases](https://pypi.org/project/uvicorn/),
[PyMuPDF releases](https://pypi.org/project/pymupdf/),
[OpenSeadragon registry](https://registry.npmjs.org/openseadragon/latest),
[Tesseract releases](https://github.com/tesseract-ocr/tesseract/releases).
