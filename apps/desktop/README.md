# AITrans Desktop

AITrans Desktop is an Electron-only React + TypeScript application.

## Runtime

```text
React / Vite Renderer
        |
        v
DesktopAdapter
        |
        +-- Electron Adapter -> preload -> allowlisted IPC -> Electron Main
        +-- Browser Adapter  -> browser-only development

Electron Main
        |
        +-- Main / Overlay BrowserWindow
        +-- file and workspace dialogs
        +-- credential vault
        +-- FastAPI process lifecycle
        |
        v
FastAPI :8766 -> Agent / RAG / Research / Memory / Sandbox
```

## Development

Canonical launcher:

```powershell
.\start.ps1
```

Explicit Electron launcher:

```powershell
.\start-electron.ps1
```

Useful modes:

```powershell
.\start-electron.ps1 -InstallDependencies
.\start-electron.ps1 -Verify
.\start-electron.ps1 -BackendOnly
.\start-electron.ps1 -BuiltRuntime
```

The branch-specific `start-electronrebuild.ps1` is retained only as a migration debug helper.

## Runtime-neutral commands

```powershell
npm run desktop:dev
npm run desktop:check
npm run desktop:verify
npm run desktop:regression
npm run desktop:build
npm run desktop:preview
npm run desktop:package
npm run desktop:make
```

## Packaging

Windows distribution uses Electron Forge plus a PyInstaller `onedir` FastAPI sidecar.
The backend lives under `resources/backend/AITransBackend/AITransBackend.exe` and
the production renderer under `resources/app.asar.unpacked/dist`.

RAG model weights are not bundled; managed models remain in the per-user AITrans model directory.

## Security boundary

Native capabilities must flow through `DesktopAdapter -> preload -> allowlisted IPC -> Electron Main`.
Agent file and command execution still flows through Workspace and Sandbox policy.
Do not expose generic renderer `fs`, `exec`, `child_process`, or raw `ipcRenderer` APIs.

## Migration history

Previous desktop launcher scripts are retained only under `docs/archive/legacy/` for historical reference.

## Release readiness

```powershell
npm run release:static
npm run desktop:release-check
npm run desktop:release-package
npm run desktop:release-candidate
```

`desktop:release-candidate` builds the Squirrel.Windows installer and writes
`out/release-manifest.json` with SHA-256 checksums. The root `VERSION` file
is the release version authority.
