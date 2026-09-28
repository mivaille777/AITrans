# AITrans Desktop

This directory contains the React + TypeScript desktop client for AITrans.

The active desktop migration target is Electron. Tauri is still retained as a
temporary fallback until the Electron manual acceptance matrix is complete.

## Runtime boundaries

```text
React / Vite Renderer
        |
        v
DesktopAdapter
        |
        +-- Electron Adapter
        |       |
        |       v
        |   preload + typed IPC
        |       |
        |       v
        |   Electron Main
        |
        +-- Browser Adapter
                |
                v
          browser-only development

Electron Main
    |
    +-- Main / Overlay BrowserWindow
    +-- file and workspace dialogs
    +-- credential vault
    +-- FastAPI process lifecycle
    |
    v
FastAPI :8766
    |
    +-- Agent Runtime
    +-- RAG / Research / Memory
    +-- Sandbox / Workspace policy

Browser Selection Bridge remains on :8765.
```

The renderer must not use Node APIs directly. Native capabilities go through
`DesktopAdapter -> preload -> allowlisted IPC -> Electron Main`.

The Python backend remains authoritative for Agent, RAG, Research, Memory and
Sandbox business logic.

## Development

### Electron development

From the repository root:

```powershell
.\start-electronrebuild.ps1
```

First run or after dependency changes:

```powershell
.\start-electronrebuild.ps1 -InstallDependencies
```

Useful Stage 9 modes:

```powershell
# Run the full local Electron verification gate, then start dev runtime.
.\start-electronrebuild.ps1 -Verify

# Run only FastAPI in the selected Conda environment.
.\start-electronrebuild.ps1 -BackendOnly

# Build the renderer/Electron main process and launch the built renderer
# through aitrans://app. This is not a packaged installer.
.\start-electronrebuild.ps1 -BuiltRuntime
```

The normal Electron launcher starts Vite and lets `BackendProcessManager` own
the FastAPI development process. Cargo is not required by this launcher.

### Legacy Tauri fallback

The repository-level `start.ps1` is intentionally retained for the existing
WebReBuild/Tauri workflow while migration acceptance is still open. Do not
remove it as part of routine Electron cleanup.

### Browser-only frontend development

From `apps/desktop`:

```powershell
npm run dev
```

## Verification

From `apps/desktop`:

```powershell
# Fast Electron-specific gate used by CI and local development.
npm run electron:check

# Full Stage 9 local verification.
npm run electron:verify

# Individual lower-level checks remain available.
npm run electron:compile
npm run test:electron-contracts
npm run lint
npm run test
npm run build
```

Windows credential smoke test:

```powershell
node scripts/electron-credential-smoke.mjs
```

Manual migration acceptance is tracked in:

```text
docs/electron-migration/manual-acceptance.md
docs/electron-migration/runtime-capability-matrix.md
```

## Frontend structure

```text
apps/desktop/
├── electron/
│   ├── main/                 # privileged Electron host
│   ├── preload/              # contextBridge surface
│   └── shared/               # IPC channel contracts
├── src/
│   ├── api/                  # FastAPI client contracts
│   ├── components/
│   ├── desktop/
│   │   ├── browser/
│   │   ├── electron/
│   │   ├── tauri/            # temporary fallback until final migration cleanup
│   │   ├── adapter.ts
│   │   └── index.ts
│   ├── features/
│   └── shared/
└── scripts/
```

## Sandbox boundary

Electron's Node.js privileges do not make Electron a direct Agent execution
surface. Agent file and command execution must continue through the existing
workspace and sandbox policy:

```text
LLM / Agent
    |
    v
Tool contract
    |
    v
Workspace + Sandbox policy
    |
    v
Sandbox runtime
```

Do not add generic renderer APIs such as `fs`, `exec`, `child_process` or
raw `ipcRenderer`.

## Sandbox feature flag

Sandbox UI is enabled by default during frontend development.

To disable the Sandbox Debug Studio and Agent filesystem workspace control at
build time:

```powershell
$env:VITE_AITRANS_SANDBOX_ENABLED="false"
npm run dev
```

If backend health supplies `sandbox_enabled`, the runtime value takes
precedence over the frontend build default.
