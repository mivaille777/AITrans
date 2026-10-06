# Electron Stage 8 Closure

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

Branch: `electronrebuild`

This document defines the Stage 8 security closure gate. It does not mark
manual desktop behavior as accepted; those checks still require a local
Windows run.

## Automated security baseline

The Electron runtime must preserve all of the following:

- Main and overlay BrowserWindows use:
  - `nodeIntegration: false`
  - `contextIsolation: true`
  - `sandbox: true`
  - `webSecurity: true`
- Renderer code receives only the typed `window.aiTransDesktop` preload API.
- Raw `ipcRenderer`, `fs`, `child_process`, and generic command execution
  are not exposed to the renderer.
- Privileged IPC uses fixed channel names and validates the sender against a
  known AITrans BrowserWindow.
- Main and overlay navigation to unexpected origins is blocked.
- The production `aitrans://app` protocol rejects renderer path traversal.
- Production renderer responses include a Content Security Policy and
  `X-Content-Type-Options: nosniff`.
- The CSP permits the local FastAPI and Selection Bridge endpoints but denies
  object/frame/form execution surfaces by default.
- Workspace selection remains a desktop picker capability only; Agent file and
  command execution must continue through backend workspace/sandbox policy.

## Local automated commands

From repository root:

```powershell
git checkout electronrebuild
git pull origin electronrebuild

cd apps/desktop
npm ci
npm run electron:compile
npm run test:electron-contracts
npm run lint
npm run test
npm run build
```

Credential smoke on Windows:

```powershell
cd apps/desktop
node scripts/electron-credential-smoke.mjs
```

## Local runtime start

From repository root:

```powershell
.\start-electronrebuild.ps1
```

For the first run or after dependency changes:

```powershell
.\start-electronrebuild.ps1 -InstallDependencies
```

The launcher intentionally does not invoke Cargo or Tauri. Electron owns the
development FastAPI child process through `BackendProcessManager`.

## Runtime verification

After Electron starts:

```powershell
Invoke-RestMethod http://127.0.0.1:8766/health
```

Expected backend identity:

```text
status  = ok
service = aitrans-backend
```

Then manually check:

- Main window start/minimize/maximize/restore/close.
- Custom titlebar drag and no-drag controls.
- Knowledge file picker.
- Agent workspace picker.
- Verified local evidence open.
- Credential save/status/preview/delete.
- Overlay show/hide.
- Overlay always-on-top.
- Overlay click-through and interactive override.
- Overlay mouse-follow/fixed placement/resize.
- Main/overlay companion events.
- Agent request.
- RAG request.
- Sandbox workspace execution.

## Process cleanup check

After closing Electron:

```powershell
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -match 'python|AITransBackend' -and
    $_.CommandLine -match 'python -m backend|AITransBackend'
  } |
  Select-Object ProcessId, Name, CommandLine
```

For an Electron-owned development backend the expected result is no orphan
`python -m backend` process.

## Stage 8 exit rule

Stage 8 is considered locally accepted only when:

1. `npm run electron:compile` passes.
2. `npm run test:electron-contracts` passes.
3. Frontend lint/tests/build pass.
4. Electron starts through `start-electronrebuild.ps1`.
5. FastAPI health is ready.
6. Main/Overlay/Files/Credentials basic manual checks pass.
7. No orphan Electron-owned backend remains after app exit.
8. The workspace/sandbox path cannot be bypassed through renderer IPC.

Do not mark Stage 9+ migration acceptance complete solely from source-level
contract tests.
