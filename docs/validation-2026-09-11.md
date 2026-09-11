# Local integration validation — 2026-09-11

Python 3.12.14, PyMuPDF 1.28.2, loopback HTTP, one PDF worker process.

Harvest's `pdf:inspect` successfully registered Soviet Life February 1961,
reported 83 pages, and saved page 64's metadata, 1,285 words, text, two search
hits and a PNG. The first hit was (308.16, 767.302, 345.5825, 775.31) pt.
The OpenSeadragon demo was manually exercised for page navigation and both
“Michurinka” overlays on the original scan.

Eight opt-in downloads from the community benchmark mirror matched the byte sizes
in PyMuPDF's reference table. Checksums are pinned in `demo/fixtures.json`.
These are single observations, not a rigorous throughput benchmark. Render times
include loopback HTTP and PNG encoding at 1,000 pixels wide; registration includes
the initial network download. The second render hits the local derivative cache.

| File | Pages | Registration s | First last-page render s | Cached s |
|---|---:|---:|---:|---:|
| DB-Systems.pdf | 1,241 | 6.985 | .053 | .002 |
| PyMuPDF.pdf | 478 | 2.204 | .039 | .001 |
| adobe.pdf | 1,310 | 7.704 | .043 | .001 |
| artifex-website.pdf | 47 | 8.000 | .060 | .001 |
| fontforge.pdf | 214 | 4.170 | .025 | .001 |
| pandas.pdf | 3,071 | 3.985 | .072 | .001 |
| pythonbook.pdf | 669 | 3.139 | .044 | .001 |
| sample-50-MB-pdf-file.pdf | 1 | 19.241 | .372 | .001 |

S3 tests use botocore's Stubber to verify streaming and VersionId selection;
they do not claim a live RappNews S3 integration. Legacy OCR/materialization engine
execution is outside this read milestone. No deployment was performed.

Final checks: 13 offline Python tests, one opt-in real reference test and two
PHP client tests (8 assertions) passed. After restarting with `./run.sh`, the
source registration was reused and Harvest successfully saved page 3,000 of the
3,071-page Pandas fixture. Tesseract is detected; Ghostscript and OCRmyPDF are
not installed in this read-only environment.
