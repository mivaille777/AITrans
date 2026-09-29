# Electron dependency health policy

AITrans separates runtime dependency risk from development/build-tool dependency debt.

## Runtime audit

Release readiness blocks on:

```powershell
npm run security:audit:runtime
```

This runs `npm audit --omit=dev --audit-level=high`. High/critical vulnerabilities in dependencies that belong to the application runtime must be resolved before a release candidate is accepted.

## Full audit

Use:

```powershell
npm run security:audit:all
```

The full audit includes Electron Forge, Electron Packager, Squirrel maker, rebuild tooling and their transitive installer dependencies. Some deprecated/vulnerable packages can remain in the latest stable upstream toolchain even when they are not shipped in the application bundle.

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

## Current packaging-tool constraint

The project intentionally stays on the current stable Electron Forge/Squirrel line. Deprecated transitive packages should be removed by upstream stable releases or a separately tested packaging-stack upgrade; they must not be hidden by suppressing npm warnings.
