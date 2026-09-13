# Reproduce or audit the newspaper pilot

There are three separate activities: audit saved evidence, recalculate scores without inference, or run new local analysis. The first two do not need scans, models, provider credentials or a running service. New inference is optional research work, not the production plan.

## 1. Audit the archived evidence

Start from the repository root. Use a fresh directory so historical evidence is not confused with new results:

```sh
mkdir -p work/evidence-audit
python3 - <<'PY'
import hashlib
import json
from pathlib import Path
import zipfile

archive = Path('benchmarks/newspaper/evidence-2026-09-12.zip')
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
    manifest = json.loads(bundle.read('MANIFEST.json'))
    for item in manifest:
        data = bundle.read(item['path'])
        assert len(data) == item['bytes'], item['path']
        assert hashlib.sha256(data).hexdigest() == item['sha256'], item['path']
    print(f'Verified {len(manifest)} manifested files')
    bundle.extractall('work/evidence-audit')
PY
```

This command extracts the versioned, checked-in evidence archive. Do not use it unchanged for arbitrary untrusted ZIP files.

Useful paths inside `work/evidence-audit/`:

| Path | Meaning |
|---|---|
| `MANIFEST.json` | Checksums and byte counts for archived files |
| `work/pilot/scans-manifest.json` | Original scan URLs, file names, dimensions and SHA-256 values |
| `work/pilot/alto/` | Selected source ALTO |
| `work/pilot/results/` | First run, including all page/mode ledgers and timings |
| `work/pilot/results-final/` | Repeated run; fingerprints accompany each ledger |
| `work/pilot/scores*.json` | Aggregate and per-excerpt scores |
| `work/pilot/existing-structure.json` | Existing sourceHash-matched semantic claims; not OCR |
| `work/pilot/boundary-scores.json` | Best-match overlap and kind diagnostics |
| `work/pilot/order-scores.json` | Explicit ordering anchors and pair results |
| `work/pilot/recovery.json` | Forced-timeout, retry and cache replay evidence |
| `work/pilot/health.json` | Runtime/model identity and available providers |
| `work/pilot/*-final.log` | Recorded offline and PHP integration check output |
| `benchmarks/newspaper/` | Human-transcribed excerpt and boundary references |

The archive contains source code for the pilot, but not the entire application or dependency environment. Use the repository for current code and setup. The reference image crops are review aids; `gold.json` defines the authoritative excerpt selection, including its pixel rectangle. A saved crop may include surrounding material beyond that scored rectangle.

## 2. Recalculate text scores without OCR

The scorer uses only the Python standard library. From the repository root after the extraction above:

```sh
python3 scripts/score_newspaper_pilot.py \
  --results work/evidence-audit/work/pilot/results \
  --gold work/evidence-audit/benchmarks/newspaper/gold.json \
  --output work/evidence-audit/recalculated-text-scores.json
```

Expected aggregate character error rates are approximately 0.49087 for ALTO and ALTO+layout, 0.97207 for full-page Tesseract and 0.45542 for region OCR. These are error rates, so lower is better. The small excerpt sample is deliberately difficult and cannot establish collection-wide accuracy.

Boundary/order scripts currently use fixed relative `work/pilot` paths. Run the archived versions from the isolated extraction root so those paths resolve to archived inputs without touching a live benchmark directory:

```sh
cd work/evidence-audit
python3 scripts/score_newspaper_boundaries.py
python3 scripts/score_newspaper_order.py
```

The boundary calculation reports target coverage on eight page-2 rectangles, not whole-page precision/mAP. It compares text blocks diagnostically but does not treat them as articles. The order calculation checks five page-2 anchor pairs; missing anchors fail and are not removed from the denominator.

## 3. Rerun local inference, only if needed

Use a working checkout of the full PDF Tools repository. Install application dependencies using its README and the isolated model runtime using `scripts/setup_analysis.sh`. See [runtime setup and limits](../../newspaper-analysis.md). Match the documented Python/package/Tesseract/model versions when investigating output differences; generated IDs and result IDs include versioned inputs.

Required inputs:

- Existing original scans for pages 1, 2, 3, 4, 12, 19, 21 and 25.
- A `scans-manifest.json` alongside them, with `page`, `file`, `sha256`, `width`, `height` and the original URL fields.
- Supplied ALTO named `1.xml`, `2.xml`, and so on. The evidence archive contains selected ALTO, so reacquiring the full archive is not necessary for these eight pages.

The original source collection was located at `/Users/tac/data/vault/cron-america/sn85059732/`. That is a historical acquisition location, not a portable deployment requirement. On another machine, place files in the existing acquisition/storage system and pass the actual paths. Do not build a new downloader merely to satisfy this harness. The manifest records source URLs and hashes; acquisition and rate-limit handling remain Harvest's responsibility.

Example using already acquired files, from repository root:

```sh
export PDFTOOLS_ANALYSIS_PYTHON="$PWD/work/analysis-venv/bin/python"
export PDFTOOLS_LAYOUT_MODEL="$PWD/work/models/layout_model_new.onnx"
export PDFTOOLS_ANALYSIS_DIR="$PWD/work/newspaper-cold-cache"
export PDFTOOLS_ANALYSIS_CONCURRENCY=1
export PDFTOOLS_ANALYSIS_THREADS=4
export PDFTOOLS_ANALYSIS_TIMEOUT=300

.venv/bin/python scripts/newspaper_pilot.py \
  --scans /absolute/path/to/existing-scans \
  --alto /absolute/path/to/selected-alto \
  --output work/newspaper-cold-results
```

Use a new analysis cache directory for cold timings. The runner initializes a path allowlist only if `PDFTOOLS_LOCAL_ROOTS` is not already set; clear or update an inherited allowlist when changing inputs. Input SHA-256 values must match the manifest. A changed scan is a different input, not a retry of the old source.

For a warm-cache comparison, rerun with the same inputs/cache but a different `--output` directory. This preserves original timings. Cached output retains original worker metrics, while the runner records the new request wall time and `cached:true`; do not call cached worker metrics a second inference measurement.

The two recorded historical runs contain identical content/geometry but some different worker fingerprints because warning labels and deadline handling changed. Exact result IDs should be read from each ledger. A new run using current code can correctly produce different result IDs even when its content agrees with the archived results.

## Failure recovery and contract checks

```sh
.venv/bin/python scripts/check_analysis_recovery.py \
  /absolute/path/to/existing-scans/page-0001.jp2 \
  --output work/new-recovery-check/recovery.json
```

Choose a new parent directory/cache for each cold recovery exercise. The script forces a one-second timeout, retries at 300 seconds with the same content key, then creates a new service instance to check a cache hit. The timeout request must be cold; a completed cached result bypasses work and should not time out.

The installed Harvest/Mediary PHP contract test is environment-dependent:

```sh
php scripts/check_integration.php \
  /absolute/path/to/harvest/vendor/autoload.php \
  work/pilot/results
```

Its ALTO comparison currently reads `work/pilot/alto` relative to the repository. Populate that with the corresponding selected ALTO before running. This test uses real installed PHP contracts; it is not a self-contained replacement for installing the relevant applications/bundles. Recorded successful output is preserved for audit when those dependencies are unavailable.

Application offline tests:

```sh
.venv/bin/python -m pytest -q -m 'not network'
node --check demo/app.js
php -l integrations/LocalPeriodicalTask.php
```

No provider credentials are needed for the local worker. Its result cache does not prove idempotency for any future paid provider adapter; that requires a separate integration test.

## Inspect saved ledgers in the browser

Start the local service as documented in the runtime guide and submit a scan through `POST /v1/analysis`, or run the harness against the same configured result cache. Open `/demo/`, expand “Inspect a saved newspaper analysis,” and use the returned result ID.

A ledger JSON alone does not restore the preview endpoint. The service also needs its private source mapping, an allowlisted path to the original scan and a matching checksum. The archival ZIP does not preserve a live cache or source-map registry. Replaying the original request recreates that mapping. A missing preview therefore does not mean the archived OCR evidence was lost.

The inspector demonstrates source overlays and region selection. It does not provide article editing, cross-page linkage or an Ink production implementation. Shut the temporary service down when inspection ends.
