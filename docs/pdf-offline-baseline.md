# PDF offline migration baseline

This document freezes the reader behavior that must remain unchanged while PDF.js
`6.3.289` moves from CDN loading to desktop-local assets. It is the Batch 1
reference for all later batches; it does not change runtime behavior.

## Frozen implementation baseline

- PDF.js version: `6.3.289`
- Interactive renderer: PDF.js canvas plus `TextLayer`
- Selection payload: `{ source: "pdf", text, pageNumber, left, top }`
- Native PDF iframe remains the error fallback.
- Supported zoom checkpoints: 70%, 100%, and 220%.
- Existing downstream actions: Evidence, Highlight, Note, Concept, Translate,
  and Ask AI.
- Out of scope: OCR for scanned/image-only PDFs and changes to Agent grounding
  schemas.

Before Batch 2, the runtime and worker are loaded from these baseline URLs:

- `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/6.3.289/pdf.min.mjs`
- `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/6.3.289/pdf.worker.min.mjs`

## Three-document regression corpus

Use stable local copies and record their checksums when doing the visual release
pass. Do not replace a corpus member during this migration.

| ID | Document profile | Required coverage |
| --- | --- | --- |
| PDF-EN | Born-digital English research paper | paragraphs, headings, page navigation, ordinary Latin fonts |
| PDF-CJK | Born-digital Chinese/CJK research paper | CJK glyph rendering and selectable Unicode text |
| PDF-LAYOUT | Born-digital two-column paper with rotated text or non-standard embedded fonts | reading order, rotated glyphs, complex selection geometry |

The documents may contain private research content and therefore are not checked
into the repository. For each manual run, record the local filename and SHA-256
in the release test notes.

## Baseline acceptance matrix

Run every row against all three corpus documents while online before comparing
the local-runtime and hard-offline builds.

| Behavior | Pass condition |
| --- | --- |
| Open and render | First page canvas and text layer appear without reader errors. |
| Page navigation | Previous/next page renders the requested page and clears the old selection. |
| Zoom | 70%, 100%, and 220% remain aligned; text selection overlays the rendered glyphs. |
| Text selection | Dragging text opens the selection toolbar with normalized selected text and the correct PDF page. |
| Evidence | Creates evidence with the selected text and PDF page provenance. |
| Highlight / Note / Concept | Each action uses the same current selection and page. |
| Translate | Receives the selected text; an upstream model failure must not corrupt the local selection. |
| Ask AI | Receives selection text, section context, and PDF page in Agent context. |

## Automated baseline commands

From `apps/desktop`:

```text
npm run test
npm run build
```

Automated tests protect data flow and deterministic UI state. Canvas/TextLayer
geometry and WebView behavior remain release-level manual checks because jsdom
does not perform browser layout.
