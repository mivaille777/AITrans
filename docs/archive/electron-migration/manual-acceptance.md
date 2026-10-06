# Electron Migration Manual Acceptance

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

Automated Electron contract tests are a prerequisite, not a replacement for
this checklist.

Before manual testing:

```powershell
cd apps/desktop
npm run electron:compile
npm run test:electron-contracts
npm run lint
npm run test
npm run build
```

Then start the Electron branch from the repository root:

```powershell
.\start-electronrebuild.ps1
```

Only check an item after observing it on the local Windows runtime.

## Main window

- [ ] application launches into the expected React route
- [ ] initial size is approximately 1320 x 720
- [ ] minimum size remains 960 x 600
- [ ] title bar can drag the window
- [ ] control buttons do not drag the window
- [ ] minimize works
- [ ] maximize works
- [ ] restore works
- [ ] close works

## Overlay

- [ ] initial overlay is hidden
- [ ] show and hide work
- [ ] light theme renders correctly
- [ ] dark theme renders correctly
- [ ] transparent corners are visually clean
- [ ] no native ghost caption appears
- [ ] always-on-top works
- [ ] click-through works
- [ ] interactive state disables click-through when required
- [ ] drag works
- [ ] mouse-follow placement works
- [ ] fixed placement modes work
- [ ] resize animation remains responsive
- [ ] overlay remains inside display work area
- [ ] main/overlay state synchronization works
- [ ] companion navigation handoff works

### Display matrix

- [ ] Windows 11 at 100% DPI
- [ ] Windows 11 at 125% DPI
- [ ] Windows 11 at 150% DPI
- [ ] dual monitor layout
- [ ] secondary monitor to the left of primary
- [ ] secondary monitor to the right of primary
- [ ] mixed DPI monitors, when available

## Native file operations

- [ ] knowledge file picker allows pdf/docx/txt/md/html/htm
- [ ] workspace picker returns a canonical absolute directory
- [ ] opening verified local evidence works
- [ ] non-file evidence URL is rejected
- [ ] missing local evidence file is rejected

## Credentials

- [ ] provider status works
- [ ] key save works
- [ ] masked preview works
- [ ] delete works
- [ ] restart preserves the encrypted credential
- [ ] plaintext key is absent from renderer state persistence and local settings API

## Backend lifecycle

- [ ] Electron starts the backend
- [ ] backend health reaches ready
- [ ] Agent request works
- [ ] RAG request works
- [ ] Sandbox request works
- [ ] unexpected backend exit is observable
- [ ] Electron exit does not leave an orphan backend process

Backend health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8766/health
```

## Security

- [ ] renderer has no Node `require`
- [ ] renderer has no generic `ipcRenderer`
- [ ] renderer has no generic filesystem API
- [ ] renderer has no generic command execution API
- [ ] navigation to unexpected remote origins is blocked
- [ ] workspace and sandbox policy remain authoritative

## Exit rule

Tauri cleanup may proceed only after the required Electron manual items above
are accepted and the repository regression gate is green.
