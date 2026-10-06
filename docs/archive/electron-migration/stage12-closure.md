# Electron Stage 12 — Full Regression

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

Stage 12 validates Electron as a complete AITrans desktop system rather than only as a shell.

## Automated layer

Run `npm run electron:regression` from `apps/desktop`.

The suite spans Electron contracts, React tests/build and focused backend integration coverage for health, credentials/settings, workspace, Sandbox, Agent and RAG. It writes `test-results/electron-regression.json`.

The report intentionally leaves packaged runtime and GUI manual acceptance false because those require an actual Windows desktop session.

## Manual layer

Use `docs/electron-migration/stage12-manual-acceptance.md` for Main Window, Overlay, DPI/multi-monitor, credential persistence, file/workspace dialogs, Agent/RAG/Sandbox, Built Runtime and Packaged Runtime.

## Comparison rule

`Electron Regression >= Tauri Baseline`

A source-level PASS alone is insufficient.

## Packaged runtime automation

The Stage 10 package verifier also runs a headless packaged-runtime lifecycle smoke:

```text
AITrans.exe --electron-runtime-smoke-test
  -> packaged Electron BackendProcessManager
  -> resources/backend/AITransBackend/AITransBackend.exe
  -> dedicated FastAPI port 18766
  -> health ready
  -> backend process cleanup
```

This validates the installed resource path and Electron-owned backend lifecycle without claiming GUI interaction coverage.
