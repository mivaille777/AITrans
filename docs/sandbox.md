# Python Sandbox

The Agent's `python_execute` capability runs Python in a disposable Docker
container. It is opt-in and appears in `GET /api/agent/tools` only when the
sandbox is enabled, Docker is using Linux containers, and the configured image
is available.

Build the default image from the repository root in PowerShell:

```powershell
.\scripts\sandbox\build_image.ps1
```

Set the feature flag before starting the backend:

```powershell
$env:AITRANS_SANDBOX_ENABLED = "true"
# Optional; this is the default image built by the script above.
$env:AITRANS_SANDBOX_IMAGE = "aitrans-python-sandbox:v1"
```

The backend must be restarted after changing these variables. With the flag
unset or false, or when Docker/the image is unavailable, the Python tool is not
registered. The image must use a pinned tag; `latest` is rejected.

When starting the desktop app with the development launcher, opt in explicitly:

```powershell
.\scripts\start.ps1 -Mode Desktop -SkipInstall -EnableSandbox
```

If another backend is already using port `8766`, use a free API port so the
launcher does not connect the frontend to that older process:

```powershell
.\scripts\start.ps1 -Mode Desktop -SkipInstall -EnableSandbox -ApiPort 8767
```

The launcher checks that the selected checkout contains Sandbox Debug Studio
and that the backend exposes a healthy sandbox runtime and `python_execute`.

The runtime defaults to no network and enforces a non-root user, read-only root
filesystem, dropped capabilities, no-new-privileges, 30-second execution limit,
and bounded CPU, memory, processes, logs, and output files. A command can request
one exact public hostname through the approval flow; this does not expose general
network access. These limits are not configurable through the Agent tool or
environment.

For permission, approval, command, workspace-change, and Debug Trace payloads,
see [the Sandbox API contract](sandbox-api-contract.md).
