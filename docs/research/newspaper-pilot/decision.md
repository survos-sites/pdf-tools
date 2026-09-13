# Decision: professional services for production newspaper analysis

Status: accepted direction for follow-up planning. Date: 2026-09-12. Scope: newspaper OCR, layout and article discovery across Harvest, Mediary, PDF Tools and Ink.

## Context

A page image or a searchable OCR blob is insufficient for article-level discovery. The system needs source coordinates, readable ordering, article/ad classification and links between continued fragments. Existing ALTO supplies useful evidence, but its text blocks are not semantic article boundaries.

The local feasibility study used eight already acquired pages from a 57-issue, 1,822-page Sunday Telegram batch. It confirmed that local region detection is useful and inexpensive to run, but showed missing OCR, poor decorative-text recognition, mixed source blocks, incomplete grouping and unresolved continuations. Existing Mistral semantic grouping was available; existing Mistral OCR was not.

The user chose professional production tooling, retaining this research for technical understanding and grant material. That decision governs the backlog even though the repository contains a working local pilot.

## Decision

Use professional OCR/layout services through existing Mediary orchestration and durable claims. Preserve Harvest's document/page model, asset identities, original scans and supplied text. Keep a provider-independent geometry/provenance contract and source-linked inspection in PDF Tools/Ink. Evaluate professional output against a representative reference set before treating it as authoritative article structure.

Retain the M4 implementation as a benchmark, debugging tool and demonstration. Do not turn it into the production execution platform or build a competing ingestion/job system around it.

## Alternatives considered

| Approach | Useful property | Reason it is insufficient alone |
|---|---|---|
| Existing ALTO only | No re-OCR cost; source IDs and geometry already exist | Recognition errors, reading-order errors and mixed semantic blocks remain |
| Full-page local Tesseract | Familiar open-source baseline | Empty output on one sampled dense page and poor difficult-excerpt performance |
| Local layout with region OCR | Useful candidate geometry; better recovery on some pages | Fragmented groups, overlap duplication, missed regions and substantial quality work |
| Existing semantic model over ALTO | Fits current Mediary batching and groups block references | Cannot repair mixed blocks automatically; questionable classifications and no continuation linking |
| Professional OCR/layout service | Managed execution; potentially stronger output; fits replaceable provider stage | Must still prove newspaper quality, preserve provenance and support downstream semantic assembly |

## Consequences

Engineering should focus on normalization, source preservation, evaluation, article assembly and user-facing traceability. Raw OCR API cost should be budgeted separately from human annotation, integration and curation. Vendor credits could support evaluation but are not a prerequisite for a sustainable service.

Professional output is another evidence layer, not permission to discard original ALTO. Provider boxes still need coordinate normalization and complete-group validation. Changing providers should not force a new ingestion model or erase stable source references.

No vendor selection, service contract, quality guarantee, grant amount or production deployment was made by this decision. Historical price estimates in the report are dated estimates and must be checked before future paid work.

## Reconsideration triggers

Reconsider implementation details if a representative comparison shows a materially better service, source restrictions rule out a provider, or measured production costs change the balance. Reconsider local production inference only with an explicit new requirement and operations/evaluation evidence; spare workstation RAM is not sufficient justification.

## Supporting evidence

- [Measured findings and limitations](report.md)
- [Closeout and production backlog](handoff.md)
- [Grant brief](grant-brief.md)
- [Versioned benchmark data](../../../benchmarks/newspaper/)
