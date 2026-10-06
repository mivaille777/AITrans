# Electron Migration Baseline

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

Branch: `electronrebuild`  
Source baseline: `WebReBuild`  
Initial commit: `75fad6ed75ea794d2f0489e001bf5be4b3cfac83`

## Migration rule

This branch replaces the desktop runtime, not the AITrans product architecture.

The following remain authoritative and must not be rewritten as part of the Electron shell migration:

- React/Vite renderer
- FastAPI API contracts
- Agent runtime and orchestration
- RAG and RAG Debug Studio
- Research and memory subsystems
- Sandbox and filesystem workspace policy
- Existing HTTP/SSE data paths

## Runtime migration order

1. Keep Browser + Tauri working.
2. Add Electron beside Tauri.
3. Reach feature parity.
4. Switch the default desktop runtime to Electron.
5. Remove Tauri only after regression acceptance.

## Baseline runtime boundaries

```text
React Renderer
  -> DesktopAdapter -> Tauri/browser native capability
  -> HTTP/SSE -> FastAPI :8766
  -> Browser Selection Bridge :8765

FastAPI
  -> Agent / RAG / Research / Memory / Sandbox
```

## Regression commands

Frontend:

```powershell
cd apps/desktop
npm ci
npm run lint
npm run test
npm run build
```

Backend:

```powershell
python -m pytest -q tests/api
python -m pytest -q tests/agent
python -m pytest -q tests/multi_agent
python -m pytest -q tests/integration
```

Current Tauri fallback:

```powershell
cd apps/desktop
npm run tauri:dev
```

## Non-negotiable security baseline

Electron migration must not introduce a renderer-to-Node shortcut. Production Electron windows must use a preload bridge with context isolation and a sandboxed renderer. Generic filesystem, shell, process, or arbitrary IPC primitives must not be exposed to the renderer.

Agent filesystem and command execution must continue to respect workspace registration, policy validation, sandbox boundaries, and traceability.
