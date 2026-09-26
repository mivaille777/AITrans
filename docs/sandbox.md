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

The runtime policy is fixed by the backend: no network, non-root user,
read-only root filesystem, dropped capabilities, no-new-privileges, 30-second
execution limit, and bounded CPU, memory, processes, logs, and output files.
These limits are not configurable through the Agent tool or environment.
