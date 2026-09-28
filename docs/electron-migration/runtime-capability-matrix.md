# Desktop Runtime Capability Matrix

This matrix separates **implementation**, **automated evidence**, **packaged evidence** and **manual desktop acceptance**. A source-level PASS never substitutes for real Windows interaction where native UI behavior is involved.

| Capability | Tauri baseline | Electron implementation | Automated evidence | Packaged evidence | Manual acceptance |
| --- | --- | --- | --- | --- | --- |
| Main window startup | PASS | IMPLEMENTED | compile + security/window contracts | packaged Electron lifecycle smoke | TODO |
| Main minimize | PASS | IMPLEMENTED | window-frame + IPC contracts | shell packaged | TODO |
| Main maximize / restore | PASS | IMPLEMENTED | window-frame + IPC contracts | shell packaged | TODO |
| Main close | PASS | IMPLEMENTED | window-frame + IPC contracts | packaged backend cleanup path | TODO |
| Custom title bar drag | PASS | IMPLEMENTED | drag-region contract | shell packaged | TODO |
| Overlay show / hide | PASS | IMPLEMENTED | overlay runtime contract | shell packaged | TODO |
| Overlay always on top | PASS | IMPLEMENTED | overlay runtime contract | shell packaged | TODO |
| Overlay click-through | PASS | IMPLEMENTED | overlay runtime contract | shell packaged | TODO |
| Overlay mouse follow | PASS | IMPLEMENTED | positioning/runtime contracts | shell packaged | TODO |
| Overlay fixed position | PASS | IMPLEMENTED | positioning/runtime contracts | shell packaged | TODO |
| Overlay resize | PASS | IMPLEMENTED | overlay runtime contract | shell packaged | TODO |
| Overlay cross-window events | PASS | IMPLEMENTED | overlay runtime/security contracts | shell packaged | TODO |
| Knowledge file picker | PASS | IMPLEMENTED | file IPC/service contract | shell packaged | TODO |
| Agent workspace picker | PASS | IMPLEMENTED | file IPC + filesystem workspace regression | shell packaged | TODO |
| Evidence source open | PASS | IMPLEMENTED | file IPC/service contract | shell packaged | TODO |
| Credential status | PASS | IMPLEMENTED | credential contract + Windows smoke | credential service packaged | TODO |
| Credential preview | PASS | IMPLEMENTED | credential contract + Windows smoke | credential service packaged | TODO |
| Credential save | PASS | IMPLEMENTED | credential contract + Windows smoke | credential service packaged | TODO |
| Credential delete | PASS | IMPLEMENTED | credential contract + Windows smoke | credential service packaged | TODO |
| FastAPI backend | PASS | PRESERVED | health + Stage 12 regression | packaged Electron -> sidecar -> health smoke | TODO |
| Selection bridge :8765 | PASS | PRESERVED | existing regression coverage | renderer CSP allows local bridge | TODO |
| RAG Debug Studio | PASS | PRESERVED | React + RAG offline/model-manager regression | packaged backend dependencies included | TODO |
| Sandbox Debug Studio | PASS | PRESERVED | React + sandbox debug regression | packaged backend lifecycle smoke | TODO |
| Workspace sandbox boundary | PASS | PRESERVED | workspace + sandbox regression | backend packaged | TODO |
| Agent Runtime | PASS | PRESERVED | Agent API/Python integration + Runtime acceptance CI | packaged backend lifecycle smoke | TODO |
| SSE streaming | PASS | PRESERVED | existing frontend/backend regression | backend packaged | TODO |
| Production renderer | N/A | IMPLEMENTED | protocol/CSP contracts | app.asar.unpacked/dist verified | TODO |
| Python-free target machine | N/A | IMPLEMENTED | sidecar packaging contracts | frozen sidecar + Electron lifecycle smoke | TODO |

## Automated gates

Fast Electron source gate:

```powershell
cd apps/desktop
npm run electron:check
```

Cross-stack Stage 12 regression:

```powershell
npm run electron:regression
```

Windows deliverable gate:

```powershell
npm run electron:package
```

The package verifier checks the packaged renderer, frozen sidecar and the full packaged lifecycle:

```text
AITrans.exe --electron-runtime-smoke-test
  -> BackendProcessManager
  -> resources/backend/AITransBackend/AITransBackend.exe
  -> dedicated health endpoint
  -> process cleanup
```

## Native/manual-only acceptance

The following still require a real Windows desktop session and must remain TODO until observed:

- minimize / maximize / restore / close behavior
- titlebar drag hit areas
- native file/folder dialogs
- credential persistence across real restarts
- Overlay transparency, always-on-top and click-through behavior
- DPI scaling and multi-monitor placement
- end-user Agent/RAG/Sandbox workflows in development, built and packaged runtime

Use `stage12-manual-acceptance.md` as the authoritative manual checklist.

## Exit rule

Do not switch the default runtime to Electron until:

```text
Automated Stage 12 regression PASS
AND Windows package gate PASS
AND required manual acceptance PASS
AND Electron Regression >= Tauri Baseline
```
