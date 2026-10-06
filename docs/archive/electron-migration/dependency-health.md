# Electron dependency health policy

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../start.ps1)；最新检索修复见 [语义排序报告](../../development/rag-semantic-ranking-2026-10-05.md)。

AITrans audits both application dependencies and the Electron build toolchain.

## Release audit

Release readiness blocks on:

```powershell
npm run security:audit:all
```

This runs `npm audit` and blocks CI and release candidates on any reported vulnerability, including development and packaging dependencies.

## Runtime-only check

Use:

```powershell
npm run security:audit:runtime
```

This runs `npm audit --omit=dev --audit-level=high` for a quick check of shipped dependencies. It does not replace the full release audit.

Forge 7 needs the Packager 18 callback interface. The `package.json` overrides keep that interface while replacing its vulnerable `extract-zip` dependency with Electron's maintained fork; they also pin audited versions of `@electron/rebuild`, `tmp`, and `undici`. Changes to these overrides require a clean `npm ci`, Electron regression, and a Windows package smoke test before release.

Do not use `npm audit fix --force` blindly. It can force incompatible major versions into the Electron packaging chain.

## Cache corruption recovery

If `npm ci` reports `zlib: incorrect data check` or says cached tarballs are corrupted, first run:

```powershell
npm run deps:repair
```

This verifies npm's content-addressed cache, removes invalid entries and performs a clean install preferring fresh registry responses.

If the corruption repeats after that, use the stronger local-only recovery:

```powershell
npm cache clean --force
npm ci --prefer-online
```

Cache corruption is workstation state, not a repository lockfile defect.

## Packaging-tool constraint

The project remains on stable Electron Forge and Squirrel. Deprecated packages may still produce installation warnings; the audit and packaging tests remain the acceptance checks.
