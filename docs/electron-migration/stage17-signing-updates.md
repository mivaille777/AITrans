# Electron Stage 17 — Windows Signing and Update Channels

Stage 17 adds production-safe Authenticode signing hooks and Squirrel.Windows update feeds without requiring release credentials for normal development.

## Code signing

Forge reads signing material only from environment variables:

```text
AITRANS_WINDOWS_CERTIFICATE_FILE
AITRANS_WINDOWS_CERTIFICATE_PASSWORD
AITRANS_WINDOWS_TIMESTAMP_SERVER   (optional)
```

When the file/password are absent, ordinary package/make remains unsigned and usable for development.

Production tag builds require GitHub Secrets:

```text
AITRANS_WINDOWS_CERT_PFX_BASE64
AITRANS_WINDOWS_CERT_PASSWORD
```

The PFX is decoded only into the ephemeral GitHub runner temporary directory. `*.pfx` and `*.p12` are ignored by Git.

`release:verify-signing` verifies both the packaged `AITrans.exe` and Squirrel `Setup.exe` with `Get-AuthenticodeSignature`. A production tag sets `AITRANS_REQUIRE_WINDOWS_SIGNING=1`, so an invalid/unsigned executable fails the release candidate.

Electron Forge also supports Azure Trusted Signing through `windowsSign`; that remains an optional future credential backend. The current Stage 17 implementation uses PFX secrets and the same `windowsSign` interface.

## Update channels

Channels are isolated:

```text
out/update-feed/
├── stable/win32/x64/
│   ├── RELEASES
│   ├── *-full.nupkg
│   ├── *Setup.exe
│   └── channel-manifest.json
└── beta/win32/x64/
    └── ...
```

`RELEASES` and the full `.nupkg` stay in the same directory because Squirrel.Windows reads the RELEASES metadata and fetches packages from that feed.

## Packaged update configuration

`prepare:update-config` writes `build/electron-resources/update-config.json`, which is bundled as an Electron extraResource.

Auto-update is enabled only when all of the following are true:

1. Windows
2. packaged Electron app
3. Squirrel-installed app with parent `Update.exe`
4. packaged `enabled=true`
5. non-empty HTTPS update base URL

The feed URL is:

```text
<AITRANS_UPDATE_BASE_URL>/<stable|beta>/win32/x64
```

Development builds and unsigned/local packages remain update-disabled by default.

## Runtime behavior

Electron's built-in `autoUpdater` performs the Squirrel.Windows update check.

`--squirrel-firstrun` waits 15 seconds before the first check because Squirrel holds an install lock immediately after installation.

When an update is available, Squirrel downloads it automatically. AITrans does not force `quitAndInstall()`; the downloaded update is applied on a later restart.

## GitHub configuration

Repository variable:

```text
AITRANS_UPDATE_BASE_URL=https://updates.example.com/aitrans
```

Repository secrets:

```text
AITRANS_WINDOWS_CERT_PFX_BASE64=<base64 PFX>
AITRANS_WINDOWS_CERT_PASSWORD=<PFX password>
```

Manual Release Readiness runs may omit these credentials and produce an unsigned candidate with auto-update disabled. `v*` tag releases require both signing secrets and the update base URL.

## Stage 17 exit criteria

1. Optional development signing path does not block unsigned builds.
2. Production tag release requires valid signing credentials.
3. Packaged AITrans.exe and Setup.exe signature status is Valid.
4. Stable and Beta feeds are isolated.
5. RELEASES/full nupkg update bundle is generated.
6. Auto updater starts only in explicitly enabled Squirrel installs.
7. Update feed uses HTTPS.
8. First-run lock is respected.
9. Downloaded updates do not force an unexpected restart.
10. A real old->new update is still pending until two signed versions are published to the update store.
