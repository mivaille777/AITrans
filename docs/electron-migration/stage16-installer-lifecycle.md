# Electron Stage 16 — Windows Install / Upgrade / Uninstall Lifecycle

Stage 16 validates the Squirrel.Windows installer as a real per-user Windows application lifecycle.

## Why this is separate

Squirrel.Windows installs under the current user's LocalAppData, creates versioned `app-*` directories and an `Update.exe`, and invokes the app with special lifecycle arguments during install/update/uninstall.

Because a real lifecycle test mutates the current Windows user's installation state, it is intentionally not part of normal push CI.

## Squirrel lifecycle handling

AITrans handles:

```text
--squirrel-install  -> create shortcut -> quit
--squirrel-updated  -> recreate shortcut -> quit
--squirrel-uninstall -> remove shortcut -> quit
--squirrel-obsolete -> quit
--squirrel-firstrun -> normal application startup
```

The handler runs before normal Main Window / Backend startup.

## Local lifecycle harness

First build the installer:

```powershell
cd apps\desktop
npm run desktop:release-candidate
```

Then from repository root:

```powershell
.\scripts\electron-installer-lifecycle.ps1 -AcknowledgeInstallMutation
```

The harness refuses to run if `%LOCALAPPDATA%\AITrans` already exists, so it does not silently overwrite or uninstall an existing user installation.

Coverage without a previous installer:

```text
fresh install
-> installed Electron/backend runtime smoke
-> shortcut existence
-> same-version reinstall
-> runtime smoke again
-> uninstall
-> shortcuts removed
-> isolated user-data marker retained
-> no AITransBackend orphan
```

To validate a true version upgrade:

```powershell
.\scripts\electron-installer-lifecycle.ps1 `
  -PreviousSetupPath C:\path\to\older\AITransSetup.exe `
  -AcknowledgeInstallMutation
```

This installs the previous version first and then the current candidate.

## Data retention policy

Uninstall must remove application binaries and shortcuts but must not delete user data.

The lifecycle harness uses an isolated temporary `AITRANSLATOR_DATA_DIR`, creates a retention marker, verifies it survives uninstall, and then cleans up the temporary test data unless `-KeepTestData` is supplied.

The product's real user data directory remains independent from the Squirrel install root.

## Manual CI workflow

Run:

```text
Actions -> Electron Installer Lifecycle -> Run workflow
```

`previous_setup_url` is optional. When omitted, the workflow validates fresh install, same-version reinstall and uninstall. When supplied, it validates previous->current upgrade.

The workflow uploads:

```text
test-results/electron-installer-lifecycle.json
test-results/SquirrelSetup.log
```

## Stage 16 exit criteria

1. Squirrel lifecycle contract passes.
2. Fresh install passes on a clean Windows runner.
3. Installed Electron runtime smoke passes.
4. Shortcuts are created and removed correctly.
5. Same-version reinstall passes.
6. Uninstall removes application binaries.
7. User-data retention marker survives uninstall.
8. No packaged Backend process remains after uninstall.
9. Previous->current upgrade passes once a previous installer candidate exists.
10. Clean-machine manual acceptance remains separately observable.
