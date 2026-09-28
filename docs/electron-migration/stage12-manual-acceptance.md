# Electron Stage 12 — Full Regression Acceptance

Automated checks and real desktop checks are deliberately separated. Do not mark a manual item PASS unless it was observed on Windows.

## Automated regression

```powershell
cd apps\desktop
npm run electron:regression
```

Report:

```text
test-results/electron-regression.json
```

Automated coverage: Electron contracts, React/Vitest, production frontend build, FastAPI health, LLM settings, workspace apply, Sandbox approval/debug, Agent API/runtime, Agent Python execution, RAG offline runtime/model manager, filesystem workspace service.

## Development Electron manual acceptance

Start with `./start-electronrebuild.ps1` from the repository root.

### Main Window
- [ ] application starts
- [ ] titlebar drag works
- [x] minimize works — user-verified on Electron development runtime
- [x] maximize works — user-verified on Electron development runtime
- [x] restore works — user-verified on Electron development runtime
- [x] close works — user-verified on Electron development runtime
- [ ] no unexpected native menu/frame appears

### Credential / Files / Workspace
- [ ] credential save / masked preview / persistence / delete
- [ ] knowledge file picker
- [ ] Agent workspace picker returns canonical path
- [ ] evidence source opening works
- [ ] invalid evidence source is rejected
- [ ] Agent filesystem actions remain workspace-scoped

### Agent / RAG / Sandbox
- [ ] Agent request completes with trace/events visible
- [ ] RAG request completes and RAG Debug Studio loads
- [ ] Sandbox Debug Studio loads
- [ ] sandbox Python execution works
- [ ] sandbox file access stays inside selected workspace
- [ ] sandbox approval flow works

### Overlay
- [ ] show / hide
- [ ] always-on-top
- [ ] click-through and interactive override
- [ ] drag / resize
- [ ] mouse-follow
- [ ] top / center / bottom / custom placement
- [ ] main-overlay event synchronization

### Display matrix
- [ ] 100% DPI
- [ ] 125% DPI
- [ ] 150% DPI
- [ ] dual monitors
- [ ] secondary monitor left of primary
- [ ] secondary monitor right of primary
- [ ] mixed DPI when available

## Built Runtime

Run `./start-electronrebuild.ps1 -BuiltRuntime` and verify Vite 5173 is not required, `aitrans://app` loads, and Window/Overlay/Credential/File/Workspace/Agent/RAG/Sandbox still work.

## Packaged Runtime

```powershell
cd apps\desktop
npm run electron:package
.\out\AITrans-win32-x64\AITrans.exe
```

- [ ] packaged app starts without the development Python launcher
- [ ] packaged AITransBackend.exe starts automatically
- [ ] `/health` reports the AITrans backend ready
- [ ] Agent / RAG / Sandbox work
- [ ] RAG model path is user-local
- [ ] logs/runtime data are user-writable
- [ ] closing Electron leaves no orphan AITransBackend process

## Exit rule

Stage 12 is accepted only when `npm run electron:regression` passes, Built Runtime and Packaged Runtime pass, required GUI/DPI/multi-monitor checks pass, and Electron regression is at least functionally equivalent to the Tauri baseline.
