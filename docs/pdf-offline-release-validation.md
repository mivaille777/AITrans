# PDF offline release validation

This is the reproducible release-level acceptance record for the PDF.js offline
migration. The values below were captured on 2026-09-15 from branch
`WebReBuild` after Batch 5.

## Batch 6 build evidence

Commands run from `apps/desktop`:

```text
npm run test
npm run build
npm run tauri:build
```

Results:

- Vitest: 62 test files and 261 tests passed.
- TypeScript application and test type checks passed.
- Vite production build passed.
- Tauri release build passed.
- Release executable: `apps/desktop/src-tauri/target/release/aitrans-desktop.exe`
  (11,392,000 bytes in this build).
- Tauri bundling is intentionally disabled by the existing
  `bundle.active: false` setting, so this command builds the release executable
  but no installer package.

Required files observed in `apps/desktop/dist`:

| Asset | Observed output |
| --- | ---: |
| PDF.js lazy runtime | `assets/pdf-CFKt2tum.js` (430,942 bytes) |
| PDF.js worker | `assets/pdf.worker.min-Dswkl-cV.mjs` (1,265,413 bytes) |
| CMaps | 169 files (1,167,747 bytes) |
| ICC profiles | 2 files (15,017 bytes) |
| Standard fonts | 16 files (798,046 bytes) |
| WASM and fallbacks | 13 files (1,545,074 bytes) |

Hashed filenames are build outputs and may change. Validation scripts must match
their stable prefixes and extensions rather than the recorded hash.

## Batch 7 hard-offline WebView checklist

The automated asset audit in Batch 8 proves the release has no PDF.js CDN
reference and contains every required asset class. The following visual checks
must additionally be run in the release WebView with networking disabled:

1. Close AITrans and clear or bypass the WebView cache.
2. Disable Wi-Fi/Ethernet or block outbound traffic for the release executable.
3. Start the local backend and the release executable.
4. Run PDF-EN, PDF-CJK, and PDF-LAYOUT from
   `docs/pdf-offline-baseline.md` through open, page navigation, 70%/100%/220%
   zoom, and text selection.
5. Run Highlight and Evidence and verify local persistence plus the correct PDF
   page provenance.
6. Run Translate and Ask AI. A configured cloud provider may fail while offline;
   the selection toolbar, selection context, and local knowledge write must remain
   usable.
7. Inspect WebView Network/console and backend logs. There must be no PDF.js
   request to any public host and no CMap/font/ICC/WASM 404.

Scanned/image-only PDFs remain outside this acceptance because they require OCR
and do not gain a text layer from local PDF.js packaging.
