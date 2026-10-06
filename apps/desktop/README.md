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

Run the single system launcher from the repository root:

```powershell
.\start.ps1
```

Useful modes:

```powershell
.\start.ps1 -CheckOnly
.\start.ps1 -InstallDependencies
.\start.ps1 -Verify
.\start.ps1 -BackendOnly
.\start.ps1 -BuiltRuntime
```

The launcher uses the selected Conda environment for child processes and restores
its temporary environment overrides on exit. Backend-only mode does not require
Node.js or desktop packages. Older duplicate launchers have been removed.

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

PyTorch's deeply nested license files are preserved in the sidecar's
`THIRD_PARTY_LICENSES.zip` so Squirrel.Windows can process the package within
its path-length limit.

RAG model weights are not bundled; managed models remain in the per-user AITrans model directory.

## Security boundary

Native capabilities must flow through `DesktopAdapter -> preload -> allowlisted IPC -> Electron Main`.
Agent file and command execution still flows through Workspace and Sandbox policy.
Do not expose generic renderer `fs`, `exec`, `child_process`, or raw `ipcRenderer` APIs.

## Migration history

Historical phase reports are indexed in [docs/archive/README.md](../../docs/archive/README.md).
The old executable startup scripts have been removed; they remain recoverable
from Git history. Runtime parity manifests stay at their original paths for
contract tests.

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

## Installer lifecycle

Real Squirrel.Windows lifecycle acceptance is explicit because it installs and
uninstalls AITrans for the current Windows user.

```powershell
.\scripts\electron-installer-lifecycle.ps1 -AcknowledgeInstallMutation
```

The script refuses to run over an existing `%LOCALAPPDATA%\AITrans` installation.
It validates fresh install, runtime smoke, same-version reinstall, uninstall,
shortcut cleanup, user-data retention and Backend process cleanup. Pass
`-PreviousSetupPath` to include a true previous-to-current upgrade test.
