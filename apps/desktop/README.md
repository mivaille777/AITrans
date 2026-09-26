# AITranslator WebReBuild Desktop

This directory contains the React + TypeScript desktop client used by the WebReBuild migration.

## Runtime boundaries

- React owns presentation and interaction.
- FastAPI on `127.0.0.1:8766` owns the WebReBuild business API.
- `127.0.0.1:8765` remains reserved for the existing Browser Selection Bridge.
- `DesktopAdapter` isolates React from Tauri/Electron-specific APIs.
- Normal translation stays deterministic and does not run through LangGraph.
- AI Quick Actions and Companion Chat reuse the existing provider-independent Python AI services.

## Stage 3 frontend boundaries

The main React workspace is split by feature instead of accumulating business orchestration in `App.tsx`:

```text
src/
├── App.tsx                         # composition only
├── features/
│   ├── reading/                    # browser reading-context presentation
│   ├── system/                     # runtime/backend/provider status
│   └── translation/                # translation state, behavior and workspace UI
├── components/                     # cross-feature overlay/companion surfaces
├── shared/components/              # small reusable UI primitives
├── api/                            # FastAPI client contracts
└── desktop/                        # Tauri/browser native capability adapters
```

`useTranslationWorkspace()` owns the translation workspace state and browser-selection synchronization. UI components consume the controller it returns; they do not call Tauri or translation providers directly.

## Development

From the repository root, the preferred launcher is:

```powershell
.\scripts\webrebuild-dev.ps1
```

It runs frontend lint, Vitest, and the production build before starting FastAPI and Tauri.

From `apps/desktop`, individual checks remain available:

```powershell
npm run lint
npm run test
npm run build
```

Browser-only frontend development remains available with:

```powershell
npm run dev
```

## Migrated application paths

Deterministic translation:

```text
React
  -> POST /api/translation
  -> FastAPI
  -> TranslationService
  -> existing TranslationManager
  -> TranslationProvider
```

Reading Companion:

```text
Browser selection
  -> BrowserReadingBridge :8765
  -> FastAPI :8766
  -> React / Tauri Overlay
  -> Quick Actions or Companion Handoff
  -> existing AIChatService / AITextService
```

Research Notes remain persisted by the existing SQLite `ResearchNoteStore`.

The migration intentionally reuses established normalization, cache, provider, reading-context and research-note behavior under `app/` instead of duplicating those rules in the web client.


## Sandbox feature flag

Sandbox UI is enabled by default during frontend development.

To disable the Sandbox Debug Studio and Agent filesystem workspace control at build time:

```powershell
$env:VITE_AITRANS_SANDBOX_ENABLED="false"
npm run dev
```

The frontend build flag mirrors the backend `AITRANS_SANDBOX_ENABLED` switch from the Sandbox design. If the backend health response supplies `sandbox_enabled`, that runtime value takes precedence over the frontend build default. When disabled, Agent requests always use an empty `filesystem_workspace_id`.
