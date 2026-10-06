# Electron Stage 9 — Development Runtime Closure

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

Branch: `electronrebuild`

Stage 9 standardizes local Electron development and verification. It does not
create installers or production packages; Electron Forge packaging and the
Python sidecar bundle remain Stage 10.

## Supported commands

From `apps/desktop`:

```powershell
npm run electron:check
npm run electron:verify
npm run electron:dev
npm run electron:preview
```

- `electron:check`: compile Electron main/preload and run Electron runtime
  contract tests.
- `electron:verify`: run the Electron gate, frontend lint/tests/build, and
  credential vault smoke test.
- `electron:dev`: compile Electron, start Vite, wait for renderer readiness,
  then start Electron.
- `electron:preview`: build renderer + Electron code and launch the built
  renderer via `aitrans://app`. This is a production-like renderer preview,
  not a packaged application.

## Branch launcher

From repository root:

```powershell
.\start-electronrebuild.ps1
```

Optional modes:

```powershell
.\start-electronrebuild.ps1 -InstallDependencies
.\start-electronrebuild.ps1 -Verify
.\start-electronrebuild.ps1 -BackendOnly
.\start-electronrebuild.ps1 -BuiltRuntime
```

The existing repository `start.ps1` remains unchanged as the legacy
WebReBuild/Tauri fallback.

## Development preflight

`electron:dev` rejects an already occupied Vite port 5173 instead of
silently reusing another renderer process.

Port 8766 may already be occupied only when
`http://127.0.0.1:8766/health` identifies the service as:

```text
status  = ok
service = aitrans-backend
```

A healthy existing AITrans backend is reused as an external backend.
A non-AITrans service on port 8766 is treated as a startup error.

## Process ownership

The development launcher owns Vite and Electron child processes and terminates
their process trees on exit. Electron's `BackendProcessManager` separately
owns only a backend process that it spawned. A pre-existing healthy backend is
marked external and must not be killed by Electron.

## Stage 9 exit criteria

Stage 9 is complete when:

1. `npm run electron:check` passes.
2. `npm run electron:verify` passes locally on Windows.
3. `npm run electron:dev` starts Vite + Electron reliably.
4. `start-electronrebuild.ps1 -BackendOnly` starts FastAPI independently.
5. `start-electronrebuild.ps1 -BuiltRuntime` loads the built renderer through
   `aitrans://app`.
6. Closing Electron cleans up Electron-owned Vite/backend processes.
7. Existing `start.ps1` remains intact.
8. CI Electron shell uses the same `electron:check` gate as local development.

Do not add `electron:package` or `electron:make` until Stage 10 supplies a
verified Electron Forge configuration and packaged Python backend sidecar.
