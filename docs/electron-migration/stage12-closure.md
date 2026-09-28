# Electron Stage 12 — Full Regression

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
