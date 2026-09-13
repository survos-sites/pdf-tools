# Closeout and handoff

Status: feasibility study complete; production integration not started. This document is the handoff for closing the research task. Read it with the [decision record](decision.md), [measured report](report.md), [reproduction guide](reproduction.md) and [grant brief](grant-brief.md).

## Decision to carry forward

Use professional OCR/layout services in production, coordinated through the existing Mediary workflow and durable claims. Retain the local pilot for comparative evaluation, source inspection and grant evidence. A production service must not depend on an unattended M4 workstation.

The reusable outcome is the source-preserving document ledger and integration contract. The specific local OCR engine is replaceable. Keep original scans and supplied ALTO even when a provider delivers better text. Bounding boxes locate evidence; they do not establish article identity.

## What was delivered

| Deliverable | Repository location | Status |
|---|---|---|
| Feasibility findings and limitations | `docs/research/newspaper-pilot/report.md` | Complete |
| Grant narrative | `docs/research/newspaper-pilot/grant-brief.md` | Draft material; no funding application submitted |
| Production decision record | `docs/research/newspaper-pilot/decision.md` | Records user-selected direction |
| Runtime/API guide | `docs/newspaper-analysis.md` | Documents implemented local pilot |
| Source-preserving scan analysis | `pdf_tools/analysis.py`, `pdf_tools/analysis_worker.py` | Implemented; evaluated locally |
| PDF page blocks/layout/OCR API | `pdf_tools/api.py`, `pdf_tools/engine.py` | Implemented on research branch |
| Scan/region inspector | `demo/` | Browser-checked locally |
| Mediary observation-task adapter | `integrations/LocalPeriodicalTask.php` | Contract-tested; not installed in Mediary |
| Reproducible benchmark scripts | `scripts/*newspaper*`, `scripts/check_analysis_recovery.py` | Included |
| Annotation and score JSON | `benchmarks/newspaper/` | Versioned |
| Complete original evidence snapshot | `benchmarks/newspaper/evidence-2026-09-12.zip` | Versioned, with internal SHA-256 manifest |

The ZIP is an immutable historical snapshot, not the authoritative current implementation. Follow-up documentation and code fixes belong in normal repository files. Original scan binaries and model weights are deliberately not duplicated into Git. The ZIP includes the original scan manifest with source URLs and checksums, selected supplied ALTO and the evaluated output ledgers.

## System boundaries

| System | Responsibility to retain | Required future change |
|---|---|---|
| Harvest | Acquire scans/ALTO, document/page identity, original URLs and source dimensions | Supply already acquired assets and provenance to analysis; continue independent importer fixes |
| PDF Tools | Bounded page operations, source geometry, cached results, inspection | Retain the contract; determine which vendor operations belong here versus existing Mediary provider tasks |
| Mediary | Existing Asset identity, orchestration, batching, retries and durable claims | Add the chosen professional service through its existing task/provider path |
| Shared PeriodicalStructureTask | Semantic grouping of supplied page blocks with sourceHash/coverage validation | Reuse the contract; assess quality on derived fragments and a representative sample |
| ArticleAssembler | Assembly from block-ID groups | Add explicit cross-page continuation handling in a separate scoped change |
| ArticleExporter | Export claims into article-oriented data | Add a supported source/ledger branch for the selected provider; retain provenance and uncertain evidence |
| Ink | Discovery and source-linked reading | Consume reviewed/candidate structure with scans, overlays and explicit uncertainty |

No Harvest, Mediary, shared bundle or Ink source changes were made by this pilot. No new asset registry, ingestion database or durable job queue was created. A proposed `/jobs` surface was unnecessary: Mediary already owns queued execution. The local API exposes synchronous operations and durable result/status retrieval.

## Contracts that must survive a vendor change

1. Identify the original page using existing asset/document/page identity and a verified SHA-256 of the analyzed bytes. Provider request IDs are additional provenance, not replacement asset IDs.
2. Record original-image width and height. The direct scan ledger uses `[x, y, width, height]` pixel boxes. Preserve the transform from any rotated, deskewed, resized or cropped analysis input back to that original image.
3. Retain supplied ALTO IDs where possible. Generated IDs are stable within the result namespace; use `(resultId, blockId)` for global references. Model/settings changes may produce a new namespace.
4. Keep text, lines, words, detector regions and semantic groups distinct. A region can exclude a headline; a source ALTO block can span multiple articles or ads.
5. Semantic groups reference block IDs. Each source text block must be accounted for exactly once in groups or explicit unassigned evidence. Ambiguous ownership must not disappear.
6. Retain `article`, `advertisement`, `obituary`, illustration/caption and uncertain concepts. The existing shared task uses `other` for illustration/caption with a subtype mapping. Do not manufacture obituary evidence from geometry.
7. Record the basis and review status of reading order and grouping. Detector confidence is not article correctness or calibrated editorial confidence.
8. Preserve engine/model identity, options, source hashes and raw outputs needed to reproduce or audit the transformation. Do not overwrite supplied text with corrected/provider text.
9. Build the existing `periodicalPage` sourceHash with the exact PHP JSON encoding expected by consumers. Equivalent-looking JSON with different encoding/order can produce a different hash.
10. Never label a local observation as `ocr_mistral`. Claim source identity must describe the process actually used.

## Operational state and side effects

The pilot ran on localhost port 5013 for evaluation. That URL is a temporary convenience, not a hosted deliverable. Repository documents, scores and the evidence ZIP are the durable handoff. Restart instructions are in the runtime guide; do not depend on the original chat or a running local service.

No paid OCR calls, provider batch submissions, vendor-credit requests, emails, grant submissions, deployment, live claim writes or production ingestion changes were performed. Existing Mistral semantic claims were read for comparison. They are not an OCR baseline.

Closeout verification: all 114 files in the evidence manifest passed byte-count/SHA-256 verification; text, boundary and reading-order scores were recalculated from the archive without OCR or network access. Research-document links and diff whitespace checks passed. The temporary localhost preview service was stopped and port 5013 was confirmed to have no listener.

Code and evidence are on the `research/newspaper-pilot` branch in `survos-sites/pdf-tools`, with [draft PR #1](https://github.com/survos-sites/pdf-tools/pull/1). The research task can close while that draft remains available. Closing this task does not merge the PR, deploy the service or authorize the production backlog below.

## Evidence sufficient for this closeout

- Eight pages, four modes, two runs; the 32 repeated outputs retained identical text, geometry and groups.
- Six manually transcribed excerpts and eight manually traced boundary targets, plus five reading-order anchor relationships.
- A real timeout followed by same-key retry and durable cache replay from a new service instance.
- 21 passing offline tests; one opt-in network test excluded.
- 32 installed PHP contract checks, including supplied ALTO compatibility with Harvest's parser.
- Browser verification of overlays and selected-region transcription.

These establish a working local evaluation harness and expose important failures. They do not establish production article quality, representative collection accuracy, GPU performance, reboot/power-loss durability or a professional-service quality comparison. See the report for methods and numeric results.

## Production backlog, in dependency order

| Step | Concrete output | Completion evidence |
|---|---|---|
| 1. Representative reference set | Pages across multiple issues, independently checked text/regions/order/continuations | Dataset includes dense print, small ads, damage, illustrations and difficult continuations; disagreement is recorded |
| 2. Professional-service comparison | Same pages analyzed by selected service(s), including an OCR baseline | Source hashes match; raw outputs retained; quality and billed cost measured against the reference set |
| 3. Normalize vendor output | Adapter into the ledger and existing claim workflow | Coordinate transforms round-trip correctly; IDs and source coverage validate; provider labels map explicitly |
| 4. Fragment mixed source blocks | Derived line/region blocks retaining parent IDs and source text references | No silent dropped/duplicated source evidence; overlap conflicts are represented |
| 5. Semantic page grouping | Existing Mediary grouping task over suitable blocks | Correct complete boundaries and kinds measured; low-quality groups quarantined |
| 6. Issue-level continuation linking | Explicit links connecting article fragments across pages | Links checked against held-out continuation examples; uncertain links remain visible |
| 7. Export and Ink consumption | Source-linked article/ad discovery using supported claim sources | Users can open every result against the correct scan and inspect its provenance |
| 8. Production operations | Bounded service execution and idempotent paid submission | Disconnect/retry and uncertain-submit scenarios cannot silently duplicate paid work; archival results survive local-cache loss |

Do not choose acceptance percentages from this eight-page study. Set them after the representative reference set exists, according to intended research/discovery use. A future implementation task should name its provider, budget, acceptance criteria and deployment scope explicitly.

## Known technical limitations to retain in future reviews

The local model does not reliably distinguish cartoons from ads. It does not join headlines and bodies into complete articles, identify obituaries reliably, or join continuations. ALTO blocks frequently span several detected regions. Region OCR can omit undetected text and duplicate overlapping text. Full-page Tesseract returned an empty result on one sampled page. No local preprocessing bake-off was completed.

The local result cache is keyed by complete requests, not shared pipeline stages. File writes are atomic and file-fsynced, but filesystem power-loss and whole-host reboot behavior were not tested. Corrupt existing JSON is not automatically repaired. Memory measurements are subprocess RSS bounds, not whole-machine sampled peaks. Input limits/concurrency bound the pilot, but they are not evidence of production hostile-input hardening.

The PHP adapter requires an existing workflow context with local file paths and hashes; it is not a remotely portable vendor adapter as written. The live exporter does not consume its new claim automatically. Provider input restrictions, privacy/retention terms, service limits, retries and price must be checked at professional-service selection time. Local-cache idempotency does not by itself prove paid-provider submission idempotency.

## Closure rule

Close this research task after documentation and evidence are pushed and discoverable. Reopen only for a specific follow-up such as a funded vendor comparison or a scoped production adapter. There is no reason to keep optimizing the M4 baseline as an implicit background project.
