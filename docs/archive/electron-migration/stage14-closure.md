# Electron Stage 14 — Legacy Runtime Removal

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

Stage 14 removes the previous desktop runtime from every active product path.

## Removed from active code

- native legacy shell source tree
- legacy renderer adapter and runtime detection
- legacy npm dependencies and scripts
- legacy CI shell job
- legacy drag attributes
- legacy backend CORS origins
- legacy desktop build/verification commands

## Historical archive

Old launcher scripts are preserved under `docs/archive/legacy/` only for historical reference.
They are not supported execution paths.

## Canonical runtime

`DesktopRuntime = browser | electron`

Canonical launch is `./start.ps1`, which forwards to `./start-electron.ps1`.

## Acceptance truth

The project owner explicitly requested Stage 14 removal before every manual Stage 12 parity item was marked complete.
The parity manifest therefore records runtime removal while keeping `manual_parity_complete=false`.

## Verification

```powershell
cd apps\desktop
npm ci
npm run desktop:check
npm run desktop:regression
npm run desktop:build
```
