# Electron Stage 15 — Stabilization and Release Readiness

Stage 15 turns the Electron-only migration result into a repeatable Windows release candidate process.

## Version authority

The repository root `VERSION` file is the release version authority.

Current release version:

```text
0.1.0
```

The release static gate requires the same version in:

- `VERSION`
- `apps/desktop/package.json`
- `apps/desktop/package-lock.json`
- `pyproject.toml`

FastAPI reads the bundled VERSION at runtime through `backend.version.get_app_version()`.
PyInstaller includes VERSION in the frozen backend, and the staged sidecar manifest also records the version.

## Local release gates

```powershell
cd apps\desktop
npm run release:static
npm run desktop:release-check
npm run desktop:release-package
npm run desktop:release-candidate
```

`desktop:release-candidate` produces the Squirrel.Windows installer plus:

```text
apps/desktop/out/release-manifest.json
```

The manifest records version, commit, artifact size and SHA-256 for Setup.exe, full nupkg and RELEASES.

## CI

The required Electron shell CI runs `npm run release:static` after the normal Electron contract gate.

A dedicated workflow exists at `.github/workflows/electron-release-readiness.yml`.
It can be started manually or by pushing a `v*` tag.

For tag builds, the tag must exactly match VERSION:

```text
VERSION = 0.1.0
tag     = v0.1.0
```

The workflow builds and uploads a release candidate but intentionally does not publish a GitHub Release.

## Stage 15 exit criteria

1. Electron-only static release gate passes.
2. VERSION is consistent across desktop, Python project and frozen backend.
3. Full Electron regression passes.
4. Production build passes.
5. Squirrel installer passes package verification.
6. release-manifest.json is generated with SHA-256 checksums.
7. Release Readiness workflow uploads the candidate artifacts.
8. Publishing remains an explicit project-owner action.
