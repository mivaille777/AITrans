# Electron Migration Manual Acceptance

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

## Security

- [ ] renderer has no Node `require`
- [ ] renderer has no generic `ipcRenderer`
- [ ] renderer has no generic filesystem API
- [ ] renderer has no generic command execution API
- [ ] navigation to unexpected remote origins is blocked
- [ ] workspace and sandbox policy remain authoritative
