# Desktop Runtime Capability Matrix

This matrix separates **implementation**, **automated verification** and
**manual desktop acceptance**. Source-level or contract tests do not replace
manual Windows validation.

| Capability | Tauri baseline | Electron implementation | Automated verification | Manual acceptance |
| --- | --- | --- | --- | --- |
| Main window startup | PASS | IMPLEMENTED | compile + security contract | TODO |
| Main minimize | PASS | IMPLEMENTED | window-frame contract | TODO |
| Main maximize / restore | PASS | IMPLEMENTED | window-frame contract | TODO |
| Main close | PASS | IMPLEMENTED | window-frame contract | TODO |
| Custom title bar drag | PASS | IMPLEMENTED | window-frame contract | TODO |
| Overlay show / hide | PASS | IMPLEMENTED | overlay runtime contract | TODO |
| Overlay always on top | PASS | IMPLEMENTED | overlay runtime contract | TODO |
| Overlay click-through | PASS | IMPLEMENTED | overlay runtime contract | TODO |
| Overlay mouse follow | PASS | IMPLEMENTED | positioning/runtime contracts | TODO |
| Overlay fixed position | PASS | IMPLEMENTED | positioning/runtime contracts | TODO |
| Overlay resize | PASS | IMPLEMENTED | overlay runtime contract | TODO |
| Overlay cross-window events | PASS | IMPLEMENTED | overlay runtime/security contracts | TODO |
| Knowledge file picker | PASS | IMPLEMENTED | no dedicated E2E gate yet | TODO |
| Agent workspace picker | PASS | IMPLEMENTED | no dedicated E2E gate yet | TODO |
| Evidence source open | PASS | IMPLEMENTED | no dedicated E2E gate yet | TODO |
| Credential status | PASS | IMPLEMENTED | credential contract + Windows smoke | TODO |
| Credential preview | PASS | IMPLEMENTED | credential contract + Windows smoke | TODO |
| Credential save | PASS | IMPLEMENTED | credential contract + Windows smoke | TODO |
| Credential delete | PASS | IMPLEMENTED | credential contract + Windows smoke | TODO |
| FastAPI :8766 | PASS | PRESERVED | backend/CI regression | TODO |
| Selection bridge :8765 | PASS | PRESERVED | existing regression coverage | TODO |
| RAG Debug Studio | PASS | PRESERVED | frontend/backend regression | TODO |
| Sandbox Debug Studio | PASS | PRESERVED | frontend/backend regression | TODO |
| Agent Runtime | PASS | PRESERVED | Agent Runtime acceptance CI | TODO |
| SSE streaming | PASS | PRESERVED | existing regression coverage | TODO |

## Current automated Electron gate

```powershell
cd apps/desktop
npm run electron:compile
npm run test:electron-contracts
node scripts/electron-credential-smoke.mjs
```

The dedicated Electron contract suite covers runtime selection, BrowserWindow
security settings, preload surface restrictions, IPC channel/sender contracts,
overlay runtime behavior, credential contracts, backend process contracts and
the production `aitrans://app` protocol.

## Overlay acceptance environments

At minimum validate:

- Windows 11, 100% DPI
- Windows 11, 125% DPI
- Windows 11, 150% DPI
- dual monitors
- monitor positioned left of primary
- monitor positioned right of primary
- mixed DPI when available

Do not remove the Tauri fallback until the required manual Electron acceptance
items are checked and the full regression gate remains green.
