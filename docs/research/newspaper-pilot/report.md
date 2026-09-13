# Sunday Telegram: local OCR/layout pilot

Production direction: use professional OCR/layout services through Mediary. Preserve supplied ALTO and original scans as the foundation, and keep this local pilot as a feasibility study, vendor-comparison baseline and grant evidence. Neither the tested local model nor existing Mistral structure claims are reliable enough to publish complete articles unattended.

The working pilot is included in this repository; see [setup and integration instructions](../../newspaper-analysis.md). It supplies local scan analysis, durable results/status, PDF blocks/layout/OCR operations, and a clickable scan/region inspector. It includes an app-level Mediary task adapter tested against the installed Harvest contracts. It does not modify the live Harvest/Mediary/Ink applications or start imports, provider batches, or paid calls.

After starting the service locally, use `/demo/` to inspect saved results and `/docs` for the OpenAPI reference. [Archived benchmark evidence](../../../benchmarks/newspaper/evidence-2026-09-12.zip) contains the measured results.

## Evaluation scope

Archive inventory: 57 issues / 1,822 ALTO pages in `wvu_oliver_ver01.tar.bz2`. Thirty original JP2 scans were already cached for the issue identified as `sn85059732-1914-11-29-ed-1`. The pilot reused eight of those scans: pages 1, 2, 3, 4, 12, 19, 21 and 25. No additional LOC/image-metadata requests were made.

The sample covers dense columns, damaged type, small classifieds, illustrated features, captions, display ads and explicit “continued from page one” material. It is limited to one issue; it is not a representative sample across all 57 issues. Page 2's printed masthead says Saturday, November 28; the capture's issue identity says November 29. Keep source identity and printed evidence rather than silently correcting that discrepancy.

Machine: Apple M4 Pro, 48 GiB RAM. One analysis worker, four CPU threads, ONNX CPU execution. Available ONNX providers include CoreML, but GPU/ANE acceleration was not used or benchmarked. Tesseract 5.5.3; Pillow 12.3.0; NumPy 2.5.3; ONNX Runtime 1.30.0. Model: pinned American Stories YOLO ONNX, SHA-256 `045b2e5588e53c700490730244bdc3e8ff21e903aff1c2af9b169dcdb1d9155e`.

Each of four approaches ran on all eight pages, then ran again. The 32 repeated results had identical blocks, text, boxes and groups. Worker warning/order-label/deadline handling changed between runs; each result records its exact worker/model/runtime fingerprint. Timing variation is reported as a range, not averaged into false precision.

## Throughput and memory

| Approach | Mean seconds/page, two runs | Largest conservative memory bound | 1,822 pages, compute only | Eight hours at 50% duty |
|---|---:|---:|---:|---:|
| Supplied ALTO, no OCR | 1.27–1.46 | 0.17 GiB | 0.65–0.74 h | All pages |
| ALTO + local layout/candidate associations | 1.90–2.09 | 0.98 GiB | 0.96–1.06 h | All pages |
| Full-page Tesseract, PSM 3 | 15.0 | 0.66 GiB | 7.6 h | About 960 pages |
| Local layout + region Tesseract, PSM 6 | 17.7–19.4 | 1.12 GiB | 9.0–9.8 h | About 740–815 pages |

These include local scan copying/decoding, runtime fingerprinting, inference and durable JSON writing. They exclude scan acquisition, semantic grouping, claim export and article search indexing. The ALTO route still decodes the image to establish source geometry; a metadata-only path could be faster. Do not extrapolate linear gains from more workers without testing CPU contention.

Memory is the sum of the worker's maximum RSS and the largest OCR child's maximum RSS, not a sampled simultaneous whole-machine peak. It excludes the web service and the user's other applications. It is deliberately conservative for the subprocess tree, but does not establish a total-process budget.

Compact ledgers project to approximately 1.6–1.8 GiB per full-batch ALTO/layout/region-OCR variant. Retaining all four variants is around 6.4 GiB before operational margin. Set `PDFTOOLS_ANALYSIS_BYTES=8589934592` for an all-variant experiment, or archive successful results through Mediary and prune deliberately. The default 2 GiB cache stops with 507 rather than evicting durable results silently.

## Text accuracy: small, difficult excerpt test

Six independently transcribed scan crops contain 169 reference words. Scoring uses lowercase NFKC and collapsed whitespace; punctuation and printed line-end hyphens remain. Words are selected by their centers within the reference crop and retained in engine order. Missing words, duplicate OCR, broken ordering and noise therefore all increase error. This is an end-to-end excerpt test, not recognition-only accuracy or a full-page gold corpus.

| Approach | Character error rate | Word error rate |
|---|---:|---:|
| Supplied ALTO | 49.1% | 75.7% |
| ALTO + layout | 49.1% | 75.7% |
| Full-page Tesseract | 97.2% | 100.0% |
| Region OCR | 45.5% | 88.8% |

These high rates are real warning signs, but the tiny sample emphasizes damaged advertisements and headings. They must not be advertised as collection-wide accuracy. ALTO wins some excerpts; region OCR improves the damaged page-12 advertisement body but loses other headings. The large illustrated page-25 headline is especially poor in region OCR, with spurious marks and duplicate/extra output. ALTO+layout deliberately leaves transcription unchanged.

The full-page baseline returned **zero words on page 4**; region OCR returned 4,960 versus 5,013 supplied ALTO words. Word count is not accuracy, but this is a practical failure that must be surfaced. The worker now warns on empty OCR. Region OCR also warns that detections can omit text or overlap, so it cannot replace source text automatically.

No preprocessing bake-off was performed. Contrast normalization, binarization, deskew and alternative Tesseract segmentation settings remain possible improvements; their benefit is unmeasured here.

## Reading order and boundaries

Five manually chosen page-2 order relationships test headline/deck/body ordering, the transition into a second column, a photo headline/caption pair and a short article. ALTO passes 4/5, full-page Tesseract 3/5, and region OCR 4/5. ALTO places the photo caption before its headline. Both Tesseract approaches place the second column of the coal-famine article before its first-column body. An anchor can contain OCR noise, so these counts are a small ordering diagnostic, not full-page validation.

The page contains explicit continuations (“Austrians” and “No Sweeping,” both from page one). No tested local result or existing page-scoped structure claim supplies cross-page links: **0/2 continuation relationships are assembled**. The existing ArticleAssembler also does not join them. Full article-level search therefore remains downstream work.

Eight manually traced page-2 targets cover five complete ads, two short articles and a combined illustration/headline/caption. Matching uses intersection-over-union (IoU) against each target's outer rectangle. Counts are target coverage, not whole-page precision or mAP.

| Representation | Mean best IoU | Targets with IoU ≥ 0.5 | Correct kind and IoU ≥ 0.5 |
|---|---:|---:|---:|
| ALTO text blocks, diagnostic only | 0.428 | 2/8 | Not article classes |
| Tesseract text blocks, diagnostic only | 0.165 | 0/8 | Not article classes |
| Local detector regions | 0.808 | 7/8 | 1/8 |
| ALTO + local candidate groups | 0.298 | 3/8 | 0/8 |
| Region OCR + local candidate groups | 0.644 | 6/8 | 1/8 |
| Existing Mistral semantic groups on ALTO | 0.371 | 2/8 | 2/8 |

The detector finds geometry well on these targets. Its combined cartoon/advertisement label is intentionally uncertain, and an article region often excludes its headline. Detector regions are **not complete article boundaries**. Likewise, an ALTO text block can cross multiple semantic regions: local association leaves 242 of 282 original ALTO blocks unassigned across eight pages. Region OCR leaves 40 of 989 blocks unassigned, but this lower count does not mean better article assembly; many groups are fragments, and overlap can duplicate text.

## Existing Mistral results and new-call estimate

Thirty existing `ai:periodicalStructure` claims were found, with eight matching sampled pages by exact sourceHash. They are `mistral-small-2603` semantic grouping of supplied ALTO, **not Mistral OCR**. No existing OCR baseline was found in the inspected dataset claims. Consequently, OCR quality, latency and memory cannot be compared against Mistral in this pilot.

Existing semantic groups contain useful associations, but the stored coverage warnings show quarantined groups and omitted blocks. Page 1 includes a murder-trial story classified as an obituary. Do not equate a claim's confidence field with human-validated article accuracy.

Current Mistral OCR 4.1 standard pricing is $4 per 1,000 pages; annotated pages are $5 per 1,000. Eight new OCR pages would be **$0.032**; all 1,822 would be **$7.29**, or **$9.11 annotated**. These are list-price arithmetic, before tax, retries, additional semantic-model calls and any provider-specific billing conditions. No cache/batch discount is assumed. No paid request was submitted. [Mistral OCR 4.1 pricing](https://docs.mistral.ai/models/ocr-4-1)

At that price, a small paid comparison is worth doing before substantial local OCR tuning. The unproven stage is newspaper quality/assembly, not whether this batch's OCR requires a $1,000 budget.

## Smallest adapter and deployment boundary

The inspected integration points were Harvest's AltoParser, ArticleAssembler and ArticleExporter; the shared PeriodicalStructureTask contract; PDF Tools' existing cached page operations; and Mediary's PeriodicalStructureQueue, asset task runner and claim interfaces.

The resulting adapter is `integrations/LocalPeriodicalTask.php`. It is an ObservationTask returning a TaskResult with `ai:pageAnalysis`; Mediary can execute and persist it through its existing workflow. Existing Asset URLs/IDs remain authoritative. The adapter also produces the existing `periodicalPage` context for semantic batches, with PHP's exact JSON/sourceHash encoding. Thirty-two result contracts passed the installed validator; ALTO block IDs/text/coordinates matched Harvest's parser.

No parallel ingestion/job database is introduced. `POST /v1/analysis` is a synchronous, bounded operation over an already acquired scan. Mediary owns queued/running/retry orchestration. PDF Tools supplies content-keyed durable result/status endpoints. The API takes an allowlisted local path and verified SHA-256; an existing Asset ID resolves to those at the app boundary.

The adapter is supplied and validated, **not registered in the running Mediary application**. ArticleExporter currently has an existing-Mistral-source branch; it needs an explicit local-ledger source branch before these claims become exported articles. Ink was not modified; the running PDF Tools viewer demonstrates consumption of the same ledger and overlays. This is a working evaluation pilot, not a completed unattended article-search rollout.

## Resilience checks

- Forced one-second timeout: failed with actionable 504 in 1.06 seconds.
- Retry: same result ID, attempt 2 completed, 3,528 OCR words.
- Fresh service instance: durable cache hit in 0.065 seconds with identical output.
- Unit tests: allowlist/checksum rejection, block coverage/ambiguity, ALTO coordinate scaling, explicit OCR requirement, cross-process slot exhaustion and stale-running status.
- Final offline suite: 21 passed; one opt-in network test excluded. All 32 PHP integration contract checks passed. Browser inspection verified clickable regions and matching transcription; JavaScript syntax and diff whitespace checks passed.

Per-result locks and concurrency slots are inherited by workers; a lost parent does not immediately allow duplicate computation. Workers kill their process group at their deadline. Atomic, file-fsynced results survive ordinary service restarts. Sudden-power-loss filesystem durability and a real whole-host reboot were not tested. An existing corrupt cache file is not automatically healed. Complete requests are cached; shared intermediate model results across different requests are not yet a component cache.

## Recommendation

1. **Use supplied ALTO and source scans immediately.** Preserve original IDs/coordinates/text as evidence, independent of every later model output.
2. **Use professional services for production OCR/layout.** Retain local layout as a research baseline and inspection tool, not an M4 production dependency. Keep vendor classes/confidence and detector boxes separate from article groups.
3. **Before bulk semantic grouping, split mixed ALTO blocks into derived line/region fragments with parent/source references.** Do not relabel entire ALTO blocks as articles. Preserve unassigned lines and overlap conflicts. This is the most useful next adapter improvement; it was not silently introduced into the benchmark.
4. **Keep semantic grouping in existing Mediary batches.** Apply block coverage and sourceHash checks, quarantine uncertain classifications, and add a separate issue-level continuation pass. Existing page-scoped groups alone cannot satisfy full article search.
5. **Use region OCR selectively.** It is a fallback for missing/bad ALTO, not a demonstrated wholesale improvement. Full-page PSM-3 Tesseract is not an acceptable default on this sample.
6. **Run the eight-page Mistral OCR comparison before further OCR investment.** Budget about four cents for the initial OCR comparison. Preserve its output as another source layer; do not overwrite ALTO. No claim of paid-quality superiority is made without those results.

Reproduction commands, API examples and setup are in the bundled `docs/newspaper-analysis.md`. The evidence bundle includes both runs, gold transcripts/boxes, extracted ALTO, source scan manifest, scores, recovery evidence, model/runtime identities and the pilot implementation. Original scan binaries remain in the existing vault.

## Grant framing

The project turns historical newspaper scans into article-level discovery while retaining auditable links to original text and page geometry. The pilot establishes a reusable, provider-independent document ledger and identifies the remaining research and curation problem: semantic boundaries, advertisement classification and cross-page continuations.

Fund professional OCR/layout processing, representative human annotation across multiple issues, vendor evaluation, accessible source-linked reading interfaces, and preservation/provenance. Budget engineering and curation separately from per-page OCR: this sample suggests raw OCR API charges may be small compared with integration and quality assurance. Request vendor credits as support for a measured comparison, with no dependence on receiving them.

Proposed deliverables: a stratified ground-truth evaluation set; reproducible vendor comparisons; a Mediary adapter with durable claims and idempotent paid submissions; source-linked article/ad search in Ink; and a documented preservation/export contract. Success should be measured by article completeness, correct boundaries, continuation-link accuracy and traceability, not OCR word count alone.
