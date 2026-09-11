# Symfony packaging and OpenAI compatibility discussion

Status: proposal for discussion, not an implemented protocol migration or a new
bundle. Investigated on 2026-09-11 against local source and official API docs.

## What already exists

No standalone `ai-tools-bundle` or `argus-bundle` was found in the inspected local
Composer projects. The working equivalent is split across:

- `survos/ai-workflow-bundle`: observation tasks including AbstractAiToolsTask,
  OcrTask and FlorenceTask. They invoke a Symfony AI Platform and map returned
  claim JSON into the existing claim/workflow system.
- Harvest's `config/packages/ai_tools_platform.yaml`: an `openresponses.ai_tools`
  platform whose base URL comes from AI_TOOLS_URL.
- `symfony/ai-open-responses-platform`: installed in Harvest. Its ModelClient
  POSTs model/input/options to `/v1/responses` by default and converts the response.
- The Python `ai-tools` service: documents `/v1/models`, `/v1/responses` and a
  claim-v1 result shape for local model/OCR observations. It also has ordinary
  non-model endpoints such as audio extraction.
- `depot-bundle` has an AiToolsService for a particular autocrop endpoint; it is
  not a general PDF client.

Therefore the observation/task infrastructure should be reused rather than
recreated inside a new PDF-specific workflow system.

## Recommended separation

Retain a typed PHP PDF client for registration, metadata, page rendering, crops,
coordinates, search and IIIF URL generation. These operations have explicit
parameters and often binary responses. Existing PdfToolsClient in Harvest is the
starting implementation.

When a second consumer needs it, extract a focused `survos/pdf-tools-bundle` (or
client package plus a thin Symfony bundle). Its scope would be configuration,
HttpClient wiring, typed requests/results/errors, streaming downloads and optional
Symfony AI tool adapters. It should not own a new queue, database, claims system,
provider catalog or S3 retention policy. Follow the monorepo's current bundle
conventions when that extraction is authorized.

OCR/analysis tasks that benefit from interchangeable model providers should use
the existing ai-workflow/OpenResponses path. Existing embedded PDF text should
retain its extraction provenance; it should not be mislabeled as a fresh OCR run.

A PDF helper exposed as a Symfony AI agent tool can call the typed client directly.
That integration does not require the HTTP service to pretend every render or
crop is a model completion.

## Three meanings of compatibility

| Meaning | Value | What it requires |
|---|---|---|
| Familiar API conventions | Easier client understanding | Versioned resources, consistent IDs/errors, list envelopes |
| OpenAI Files compatibility | Reuse file client operations | Matching upload, resource fields, list/retrieve/delete/content semantics |
| OpenResponses platform compatibility | Reuse the already configured Symfony AI bridge | Matching model invocation request and response contracts |

Our current `/v1/files` accepts JSON URLs/S3 references; OpenAI's file creation
accepts an uploaded file and purpose. A matching route name does not establish
compatibility. The current response also lacks the full OpenAI file envelope.
See [OpenAI Files](https://developers.openai.com/api/reference/resources/files).

Likewise, changing the metadata JSON to include `object: file` would not make
Symfony AI's installed OpenResponses ModelClient work: it calls `/v1/responses`.
The generic Symfony AI bridge is a different route for completion/embedding
providers; choose the bridge matching the implemented protocol. See
[Symfony Platform](https://symfony.com/doc/current/ai/components/platform.html).

## Proposed API evolution

1. Keep the current file/page/IIIF contracts working while consumer needs settle.
2. Define a consistent resource/error vocabulary and typed PHP DTOs. If adopting
   OpenAI-compatible fields, publish exactly which endpoints are compatible and
   test them with a real client. Avoid incompatible changes disguised as renames.
3. Decide whether to add standard multipart file upload plus list/content/delete.
   Preserve URL/S3 registration as an explicit extension. Do not claim arbitrary
   custom purposes or S3 request bodies are accepted by an OpenAI SDK.
4. For selected OCR/analysis operations, choose one OpenResponses facade owner:
   ai-tools delegating PDF mechanics to PDF Tools, or PDF Tools exposing a small
   adapter. Both services should not independently implement competing OCR job
   protocols. Existing ai-tools integration makes delegation an attractive option.
5. Return the observation schema expected by existing task consumers, including
   engine/source revision/page provenance. Keep document-scale scheduling and
   recoverable page-range work in Symfony Messenger.
6. Expose direct client operations as optional agent tools where useful. Agent
   tool discovery and invocation are separate from model-provider configuration.
   See [Symfony Agent](https://symfony.com/doc/current/ai/components/agent.html).

## Suggested decision

A focused PDF bundle is likely useful across Harvest, the periodical reader and
other archive consumers. First agree on its small client contract; extract it
when the second integration starts. Reuse ai-workflow-bundle for observations and
Symfony AI's installed OpenResponses bridge for actual model-style calls. Adopt
OpenAI conventions deliberately without forcing binary rendering or IIIF into a
Responses envelope.

Questions to settle together: should ai-tools delegate document OCR to PDF Tools,
and is the next consumer the periodical reader or another existing app? Neither
choice blocks publishing the current local milestone and documentation.
