# Local newspaper analysis pilot

Production direction is professional OCR/layout services through Mediary. This local implementation is retained as evaluation infrastructure and grant evidence, not an M4 production dependency.

PDF Tools is the bounded page-operation service. Harvest retains original scans, ALTO and document/page identities. Mediary retains Asset registration, orchestration, retries, provider batches and durable claims. Ink should render the returned ledger with source scans and present candidate groups for review.

This pilot adds no ingestion system, external queue, provider account or paid call. The app-level PHP adapter is supplied and checked against installed Harvest contracts; it is **not registered in the live Mediary container**. Existing imports and workflow repairs were left untouched.

## Start locally

From the pdf-tools checkout, install the normal application dependencies as in README, then:

```sh
brew install tesseract
sh scripts/setup_analysis.sh
export PDFTOOLS_ANALYSIS_PYTHON="$PWD/work/analysis-venv/bin/python"
export PDFTOOLS_LAYOUT_MODEL="$PWD/work/models/layout_model_new.onnx"
export PDFTOOLS_LOCAL_ROOTS="/Users/tac/data/vault/cron-america/sn85059732/_capture/scans-1914-11-29:$PWD/work/pilot/alto"
export PDFTOOLS_ANALYSIS_DIR="$PWD/work/pilot/cache"
export PDFTOOLS_ANALYSIS_CONCURRENCY=1
export PDFTOOLS_ANALYSIS_THREADS=4
export PDFTOOLS_ANALYSIS_TIMEOUT=300
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 5013
```

Setup downloads a ~99 MiB pinned American Stories ONNX model and verifies its SHA-256. Python package versions are pinned in `requirements-analysis.txt`. The model adapter uses NumPy and ONNX Runtime directly to retain detector confidence scores; it does not use the upstream wrapper that replaces scores with 1.0. CPU execution is explicit. `/health` reports runtime versions and available ONNX providers; an available CoreML provider does not mean this pilot runs on GPU/ANE. Model weights: [American Stories ONNX, CC-BY-4.0](https://huggingface.co/NealCaren/american-stories-onnx). Preserve attribution if distributing weights.

## Operations

OpenAPI is at `/openapi.json`, interactive documentation at `/docs`.

| Capability | Existing API plus pilot extension |
|---|---|
| Readiness | `GET /health`, `GET /v1/analysis/capabilities` |
| Existing PDF text blocks | `GET /v1/files/{id}/pages/{page}/blocks` |
| PDF page layout | `POST /v1/files/{id}/pages/{page}/layout` |
| Explicit PDF page OCR | `POST /v1/files/{id}/pages/{page}/ocr` |
| Existing local scan + supplied ALTO | `POST /v1/analysis` |
| Durable result | `GET /v1/results/{resultId}` |
| Execution status | `GET /v1/results/{resultId}/status` |
| Original scan preview | `GET /v1/results/{resultId}/image.jpg` |

No `/jobs` queue is needed. Analysis submission is synchronous: Mediary's existing task holds the queued/running/retry state. The service returns `X-Cache`, a deterministic result ID and a result Location. A disconnected caller resubmits identical input; it gets the cached result or a retryable 429 while execution still owns its lock. Status reports running/completed/failed/interrupted. Queued belongs to Mediary. Asset IDs are resolved to existing locally acquired scans by the adapter/caller, not registered afresh in PDF Tools.

Example body (substitute the actual cached scan SHA-256):

```json
{
  "imagePath": "/absolute/path/page-0001.jp2",
  "sha256": "64-lowercase-hex-characters",
  "altoPath": "/absolute/path/1.xml",
  "textSource": "alto",
  "tasks": ["layout", "group"]
}
```

ALTO-only uses `tasks:["text"]`. Full-page Tesseract uses `textSource:"tesseract", tasks:["ocr"]` without altoPath. Region OCR uses `tasks:["layout","ocr","group"], regionOcr:true`. Layout only uses `textSource:"none", tasks:["layout"]`. Reading an existing PDF text endpoint never starts OCR.

## Geometry and uncertainty

For direct scan analysis, `box` is `[x,y,width,height]` in **original-image pixels**, with original width/height, source SHA-256 and 3×3 transforms. ALTO dimensions are scaled to scan dimensions: first-page ALTO inch1200 units are 17,008×23,600; scan pixels are 4,252×5,900, a 0.25 scale. Source ALTO block IDs are preserved. Generated IDs are stable within a result keyed by source, engine/model and settings. They are page-scoped; use `(resultId, blockId)` globally. Changed models/options create a different result namespace.

The current worker performs no deskew/rotation; it reports zero/identity, and inverts detector resizing/letterboxing into source pixels. Existing source boxes extending beyond a scan are retained as supplied evidence. PDF raster analysis refers to the rendered page pixels and also reports PDF dimensions/rotation; use the direct original JP2 route for archival scan coordinates.

Every text block occurs exactly once in a candidate group or `unassignedBlockIds`. Ambiguous overlapping ownership remains unassigned. Candidate groups reference stable text block IDs and detector region IDs. The model's cartoon/advertisement class remains `uncertain`: geometry cannot reliably distinguish ads from cartoons or establish obituaries. Caption/illustration groups map to the existing `other` kind with an explicit subtype in the PHP adapter. Empty OCR produces a warning. Region OCR can miss text outside detections and duplicate text inside overlapping detections; these are explicit warnings, not silently clean transcription.

`readingOrder` is supplied ALTO order, Tesseract order, or region top-to-bottom order, labeled as unreviewed. It is not an established newspaper article order. Headlines, multi-column articles and continued stories need semantic assembly.

## Smallest integration

`integrations/LocalPeriodicalTask.php` is an app-level `ObservationTaskInterface` implementation producing `ai:pageAnalysis` through the existing `TaskResult`/`RawClaim` contract. Register it in Mediary when integrating, supply `localPageAnalysis` on the existing Asset's workflow context, and let existing Messenger execution/persistence handle it. Do not run local HTTP analysis through a remote provider batch interface.

For semantic grouping, `LocalPeriodicalTask::structureRequest()` produces the same `periodicalPage` context consumed by `PeriodicalStructureTask` and `PeriodicalStructureQueue`. It uses PHP's exact JSON encoding to compute sourceHash. Existing ALTO blocks compare equal to Harvest's `AltoParser`; don't re-key them. Submit prepared requests through the existing queue only when paid semantic work is authorized, using existing batch submission/apply and claims. Never label local observations as `ocr_mistral`.

`ArticleAssembler::assembleStructured()` already consumes block-ID groups, but it does not join continued articles across pages. `ArticleExporter` currently reads the existing Mistral OCR claims/source and enforces issue coverage. It does **not** automatically consume `ai:pageAnalysis`. The next integration change is one explicit local-ledger source branch plus sourceHash validation, preserving original ALTO and handling `other`/uncertain/unassigned evidence. Ink can read the same claim and draw normalized overlays; the PDF Tools demo supplies a working inspector now. No Ink application changes were made.

## Overnight controls

Content hash + ALTO hash + worker code + model hash + runtime versions + Tesseract language-data hash + options determine idempotency. Durable JSON writes are atomic and file-fsynced. Per-result locks and cross-process concurrency slots prevent duplicate local computation. Workers inherit lock descriptors, so a service crash cannot immediately spawn a duplicate while an orphan finishes. The worker also kills its process group at its deadline. Per-page timeout defaults to 300 seconds; concurrency defaults to one with four CPU threads. 429 means back off; 409 means fix source identity; 422 means inspect the per-result error file; 504 means retry/adjust the page timeout; 507 means archive results or increase storage.

`PDFTOOLS_ANALYSIS_BYTES` defaults to 2 GiB for durable JSON results with no silent eviction. Temporary decoded images and inference memory are separately bounded by concurrency and a 60-million-pixel input limit. `PDFTOOLS_MAX_SOURCE_BYTES` defaults to 512 MiB. Retain/ship successful ledgers into Mediary's durable claims/object storage before pruning the local cache. The cache covers complete requests; it is not yet a shared component/DAG cache between differing requests. No paid code path exists in the local worker, so replay cannot duplicate paid work. Paid semantic grouping must continue to use Mediary's existing batch/claim identity.

## Reproduce the evaluation

Scans must already be acquired. This reads the existing manifest and archive; it makes no LOC metadata calls.

```sh
.venv/bin/python scripts/extract_pilot_alto.py /Users/tac/data/vault/cron-america/sn85059732/_capture/wvu_oliver_ver01.tar.bz2
.venv/bin/python scripts/newspaper_pilot.py --scans /Users/tac/data/vault/cron-america/sn85059732/_capture/scans-1914-11-29 --alto work/pilot/alto
.venv/bin/python scripts/score_newspaper_pilot.py
php scripts/check_integration.php
.venv/bin/python -m pytest -q -m 'not network'
```

Use a fresh `PDFTOOLS_ANALYSIS_DIR` for cold timings; preserve the original benchmark file when measuring cache replay. Gold excerpts and manually traced boundaries live in `benchmarks/newspaper/`. Excerpt scoring is lowercase NFKC with collapsed whitespace, retains punctuation and printed line-break hyphens, and penalizes missed/duplicate text in native reading order. It is a six-excerpt smoke test, not publication-grade OCR accuracy. All eight pages are from one issue because only that issue's 30 scans were already cached; broader acquisition remains Harvest's job.

Run `scripts/check_analysis_recovery.py /absolute/path/page-0001.jp2` with the configured runtime for a real one-second timeout followed by retry and a new-service cache hit. Its `recovery-cache` must be fresh. `scripts/score_newspaper_boundaries.py` consumes the benchmark and the offline matched `existing-structure.json` snapshot; it measures eight manually traced page-2 targets, not whole-page mAP or complete article recall.
