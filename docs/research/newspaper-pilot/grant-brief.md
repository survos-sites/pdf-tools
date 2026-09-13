# From newspaper scans to source-linked article discovery

Build a preservation-first newspaper research service that turns scanned pages into searchable articles, advertisements, obituaries and illustrated features, while retaining the original scans, supplied OCR and coordinates as auditable evidence.

The Sunday Telegram collection provides a concrete pilot: 57 issues and 1,822 pages. An eight-page local feasibility study showed that open-source tools can identify useful regions, but text blocks are not articles and continued stories remain unresolved. The study produced a reusable document ledger, benchmark scripts and a viewer for inspecting text against source scans.

**Production approach:** professional OCR/layout services, coordinated by existing Mediary workflows and durable claims. Harvest remains responsible for acquisition and source identity; Ink provides article discovery and source-linked reading. Local inference remains a research baseline, not production infrastructure.

**Funding priorities:** representative human annotation; comparative vendor evaluation; reliable article/ad segmentation and cross-page continuations; service integration and quality assurance; accessible reading interfaces; preservation and reproducible exports. Raw OCR charges should be itemized separately from the larger engineering and curation effort.

**Evaluation:** character/word error, reading order, region overlap, complete-article boundaries, advertisement and obituary classification, continuation-link accuracy, recovery behavior and source traceability. Include difficult pages and report uncertainty explicitly.

**Deliverables:** a documented ground-truth sample; reproducible vendor comparisons; a production service adapter using existing batching and claims; source-linked article search; and an exportable provenance record linking every derived passage back to its scan and original text.

No funding amount, delivery date or quality threshold is asserted yet. Those should follow the representative annotation exercise and professional-service comparison. Vendor credits would support evaluation, but should not be a dependency of the proposed service.
