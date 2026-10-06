# Electron Stage 11 — CI and Deliverable Gate

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

Branch: `electronrebuild`

Stage 11 separates fast source-level Electron validation from heavyweight
Windows deliverable validation.

## CI layers

### Fast runtime gate

The existing main CI keeps:

```text
electron_shell
  -> npm ci
  -> npm run electron:check
  -> credential vault smoke
```

This remains a required source-level Electron contract check and continues to
run alongside the temporary Tauri fallback job.

### Deliverable workflow

A dedicated workflow lives at:

```text
.github/workflows/electron-package.yml
```

Relevant pushes and pull requests to `electronrebuild` run:

```text
npm run electron:package
```

The workflow uploads the verified unpacked Windows application directory as a
GitHub Actions artifact with 14-day retention.

## Installer workflow

Squirrel installer generation is intentionally explicit because it is slower
and produces release-like distributables.

Run the `Electron Deliverable CI` workflow manually and enable:

```text
build_installer = true
```

That path runs:

```text
npm run electron:make
```

and uploads:

```text
Setup.exe
*-full.nupkg
RELEASES
```

from the Squirrel.Windows output directory.

## Why packaging is separate

PyInstaller + sentence-transformers/transformers + Electron Forge is much more
expensive than TypeScript/Vitest contracts. Keeping deliverable CI separate
provides:

- fast feedback for normal Electron source changes,
- a real Windows package gate for migration-sensitive changes,
- downloadable binaries without committing generated artifacts,
- explicit control over installer generation,
- an independent Electron migration signal even when unrelated Python
  regression jobs fail.

## Stage 11 exit criteria

Stage 11 is accepted when:

1. Main CI `electron_shell` passes.
2. `Electron Deliverable CI / Electron Windows package` passes.
3. The uploaded unpacked package contains the frozen backend sidecar.
4. A manual installer run with `build_installer=true` passes.
5. The uploaded Squirrel artifacts contain Setup.exe, full nupkg, and RELEASES.
6. Tauri CI remains available only as migration fallback until final cleanup.
