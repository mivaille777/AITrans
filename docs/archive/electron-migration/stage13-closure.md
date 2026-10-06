# Electron Stage 13 — Default Runtime Cutover

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

Stage 13 makes Electron the default AITrans desktop runtime while retaining
Tauri as a legacy fallback.

## Default runtime

Canonical npm commands now use the runtime-neutral `desktop:*` namespace:

```powershell
cd apps/desktop

npm run desktop:dev
npm run desktop:check
npm run desktop:verify
npm run desktop:regression
npm run desktop:build
npm run desktop:package
npm run desktop:make
```

All canonical desktop commands resolve to Electron.

## Canonical launcher

From repository root:

```powershell
.\start-electron.ps1
```

This launcher is branch-neutral and is the default Electron development entry.

The following remain available during the fallback period:

```text
start-electronrebuild.ps1  -> migration/debug launcher for electronrebuild
start.ps1                  -> unchanged legacy WebReBuild/Tauri launcher
```

## Tauri fallback

Tauri is not removed in Stage 13.

Explicit legacy commands:

```powershell
npm run legacy:tauri:dev
npm run legacy:tauri:build
```

The Tauri CI job still executes, but it is `continue-on-error` and no longer
participates in the required CI quality gate. Electron shell validation remains
required.

## Runtime selection

Renderer resolution remains defensive:

```text
Electron bridge present -> ElectronAdapter
else Tauri runtime      -> TauriAdapter
else                    -> BrowserAdapter
```

Electron is therefore the launched/default product runtime, while Tauri remains
usable until Stage 14 cleanup.

## Acceptance status

Stage 13 cutover is active, but Stage 12 manual parity is not falsified or
silently closed. `stage12-parity.json` continues to record pending manual
Built Runtime, Packaged Runtime, Overlay, DPI and multi-monitor acceptance.

This means:

```text
Default runtime = Electron
Tauri fallback  = retained, non-blocking
Stage 14 removal = NOT yet allowed
```

## Stage 13 exit criteria

Stage 13 implementation is complete when:

1. `desktop:*` commands resolve to Electron.
2. `start-electron.ps1` starts Electron without branch coupling.
3. Main CI requires Electron shell validation.
4. Tauri CI remains available but non-blocking.
5. Legacy `start.ps1` is unchanged.
6. Stage 12 parity truth remains preserved.

Stage 14 may begin only after the remaining manual parity acceptance is
completed or explicitly waived by the project owner.
