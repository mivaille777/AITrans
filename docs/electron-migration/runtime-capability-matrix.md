# Desktop Runtime Capability Matrix

Use this document to compare the existing Tauri runtime with the Electron implementation.

| Capability | Tauri baseline | Electron target | Automated test | Manual test |
| --- | --- | --- | --- | --- |
| Main window startup | PASS | TODO | TODO | TODO |
| Main minimize | PASS | TODO | TODO | TODO |
| Main maximize / restore | PASS | TODO | TODO | TODO |
| Main close | PASS | TODO | TODO | TODO |
| Custom title bar drag | PASS | TODO | TODO | TODO |
| Overlay show / hide | PASS | TODO | TODO | TODO |
| Overlay always on top | PASS | TODO | TODO | TODO |
| Overlay click-through | PASS | TODO | TODO | TODO |
| Overlay mouse follow | PASS | TODO | TODO | TODO |
| Overlay fixed position | PASS | TODO | TODO | TODO |
| Overlay resize | PASS | TODO | TODO | TODO |
| Overlay cross-window events | PASS | TODO | TODO | TODO |
| Knowledge file picker | PASS | TODO | TODO | TODO |
| Agent workspace picker | PASS | TODO | TODO | TODO |
| Evidence source open | PASS | TODO | TODO | TODO |
| Credential status | PASS | TODO | TODO | TODO |
| Credential preview | PASS | TODO | TODO | TODO |
| Credential save | PASS | TODO | TODO | TODO |
| Credential delete | PASS | TODO | TODO | TODO |
| FastAPI :8766 | PASS | MUST REMAIN | existing | existing |
| Selection bridge :8765 | PASS | MUST REMAIN | existing | existing |
| RAG Debug Studio | PASS | MUST REMAIN | existing | existing |
| Sandbox Debug Studio | PASS | MUST REMAIN | existing | existing |
| Agent Runtime | PASS | MUST REMAIN | existing | existing |
| SSE streaming | PASS | MUST REMAIN | existing | existing |

## Overlay acceptance environments

At minimum validate:

- Windows 11, 100% DPI
- Windows 11, 125% DPI
- Windows 11, 150% DPI
- dual monitors
- monitor positioned left of primary
- monitor positioned right of primary
- mixed DPI when available

Do not mark the Tauri runtime removable until every Electron target in this matrix is PASS.
