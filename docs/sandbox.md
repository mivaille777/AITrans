# Python Sandbox

The Agent's `python_execute` and `command_execute` capabilities run in a
disposable Docker container. They are opt-in and appear in `GET /api/agent/tools`
only when the sandbox is enabled, Docker is using Linux containers, and the
configured image is available. `command_execute` accepts an argv array for an
allowlisted command; it does not invoke a host shell.

Sandbox Debug Studio can start its own runtime for manual runs from the page.
This does not enable Sandbox tools for Agent runs; those remain controlled by
`AITRANS_SANDBOX_ENABLED`.

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
unset or false, or when Docker/the image is unavailable, the Sandbox tools are
not registered for Agent runs. The image must use a pinned tag; `latest` is
rejected.

For manual runs, open **Settings → Sandbox Debug Studio** and click **Start
Sandbox**. Docker Desktop must be running in Linux container mode, and the image
above must already be built. Starting the Studio runtime applies only to the
current backend session. Each **Run** starts a short-lived isolated container
and removes it when execution ends.

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
