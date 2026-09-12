# Production deployment

Deployed 2026-09-11 to Dokku app `pdf-tools` on `fsn1.survos.com`, alongside ai-tools.

- Canonical API: https://pdf-tools.survos.com
- Demo: https://pdf-tools.survos.com/demo/
- Alternate domain: https://pdf-tools-fsn1.survos.com
- Health: GET /health (public); all document/API routes require the service bearer token.
- Cloudflare provides public HTTPS, forwarding to Dokku's HTTP origin, matching the ai-tools deployment pattern. There is no app-specific origin TLS certificate installed by this deployment.
- Persistent host cache: /platform/pdf-tools/cache mounted at /cache.
- Read cache budget: 4 GiB; maximum source: 512 MiB; container memory: 2 GiB; CPU limit: 2.
- Proxy send/read timeout: 600 seconds. Cloudflare's own request limits still apply; acquisition/OCR should run through background jobs for large documents.
- PDFTOOLS_PUBLIC_URL pins HTTPS links in IIIF responses behind the proxy.
- Docker image healthcheck and app.json startup check call /health.

Production credentials are configured in Dokku. A private, ignored .env.production.local in the PDF Tools checkout contains PDFTOOLS_URL/PDFTOOLS_TOKEN for local integration. Local Harvest's .env.local now uses this endpoint and token. Never commit these files, embed the token in a URL, or publish it in documentation. The demo has a token field for authenticated requests.

S3 credentials/bucket allowlists have not been configured on this new app. HTTP(S) public sources are supported now; partner S3 access needs to be provisioned when those inputs are available. Local file IDs whose sources have not been registered in production are not automatically available there.

## Validation

- Offline read/cache/API suite passes, including canonical HTTPS IIIF URLs.
- Full Linux/amd64 image built successfully with Tesseract, Ghostscript, OCRmyPDF, PyMuPDF and img2pdf.
- Container smoke test converted a generated scan to a searchable PDF and an ordered image to searchable PDF/A, checking extracted text in both outputs. These tests replaced network downloads with generated local files; they are not a partner-source test.
- Public HTTPS smoke test: /health 200, unauthenticated API 401, authenticated capabilities 200.
- Registered the pinned PyMuPDF.pdf benchmark (478 pages), retrieved page metadata/text/words and a valid 800px PNG, and verified the manifest canvas count.
- Re-deployment verifies that registered documents survive on the persistent cache volume.

## Deploying updates

`git push dokku main` builds the Dockerfile and runs Dokku startup checks. The remote is dokku@fsn1.survos.com:pdf-tools. GitHub source is survos-sites/pdf-tools; the service, repository and local checkout now share the same name.

requirements-production.txt records the exact Python versions resolved in the tested Linux image and is the Docker installation input. requirements-read.txt and requirements.txt remain development dependency inputs. Refresh the production snapshot in a Linux container, run pip check and smoke tests, and commit it together with dependency changes. Existing FastAPI/Uvicorn pins have not been upgraded by this deployment; the earlier dependency audit remains a follow-up. No GitHub Actions deployment workflow was added.

For rollback, rebuild/redeploy a known-good Git revision with Dokku; keep /platform/pdf-tools/cache mounted. Cache artifacts are disposable, but source registrations live on that volume. Durable originals and retained partner deliverables belong in managed storage, not only this cache. Legacy OCR caches are outside the read-cache quota and need monitoring/cleanup until unified cache management is implemented.
