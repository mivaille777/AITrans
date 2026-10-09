# Chat script execution and image delivery

## User flow

Type `写一个画爱心的脚本` in Chat. The request uses the existing Agent runtime and the enabled `python_execute` tool. A generated Python program runs in Docker and saves a PNG/JPEG under `/output`. The assistant message displays the actual image, execution status, duration and exit code, with **查看代码**, **下载脚本**, **下载图片** and expandable stdout/stderr.

ReAct executes within its existing tool budget. Plan–Execute displays the generated code in the plan and waits for explicit approval before execution. Self-contained plots need no selected host folder. Requests to save files into a local folder continue to use the existing workspace authorization and confirmation flow. Code-only, no-execution and explanatory requests are excluded from automatic plot routing. Disabled/unavailable Python tools are never enabled by intent recognition.

## Implementation

- Matplotlib 3.11.2, NumPy 2.5.3 and Pillow 12.3.0 are pinned in the Python sandbox image. Use Agg and save raster images; GUI windows, turtle and network package installation are unsupported.
- Original Python source is exported by the host after container teardown, under a unique manifest entry. Source files count toward existing artifact limits. Downloads return the exact executed source, rather than a newly generated code example.
- Both native function calls and structured ReAct decisions use the registered 8192-token output budget. The Plan–Execute planner also uses 8192 tokens for embedded script arguments.
- Bounded execution receipts are attached to Agent responses, snapshots and assistant messages. A SQLite sidecar table in the existing conversation database restores image/log/source cards across refreshes. Conversation deletion cascades to its receipts.
- Chat retains at most 16 execution receipts per response and 65536 characters per stdout/stderr stream, with existing secret scrubbing. This conversation retention is separate from Debug Studio's optional full-log retention.
- File requests are bound to a stored conversation, assistant message, sandbox run and manifest file ID. Link/reparse, path, size and SHA-256 checks apply to previews and downloads. Inline previews require Pillow decoding of PNG/JPEG, at most 8 million pixels; HTML/SVG are never rendered as sandbox image previews.
- Plot acceptance requires a successfully executed tool and a decoded, verified image. A filename ending in `.png` alone cannot satisfy acceptance. Actual artifacts also appear in the right-side inspector.
- Debug Studio reuses the image result card. Confirmed plan resumption emits final acceptance; the inspector replaces its prior pending acceptance row with that final receipt.

## Deployment and verification

Rebuild the image after updating:

```powershell
docker build -t aitrans-python-sandbox:v1 -f sandbox/python/Dockerfile sandbox/python
```

Restart the backend/desktop using the normal startup workflow. Docker must be running, and Python Sandbox must be enabled in Tools. The image was rebuilt and tested on the local Docker Desktop installation on 2026-10-09.

Acceptance used an isolated snapshot of HEAD plus only this feature's files, with backend `8769`, frontend `5175` and disposable QA data. The user's running application and unrelated working-tree changes were preserved. Tests cover real Docker plotting, exact-source export, nonzero exit/error retention, container cleanup, artifact ownership/tampering/expiry, decoded image validation, source output limits, native decision budget, resumed acceptance, UI escaping, lazy source retrieval and abort on unmount. Real DeepSeek Chat testing verified PNG rendering, source download byte equality, refresh recovery, and plan approval before execution.

## Current limits

This delivers static PNG/JPEG results; it does not add HTML execution, interactive plots, animation, GUI sessions or persistent notebook kernels. Chat result cards arrive after tool completion; Debug Studio remains the live telemetry surface. The existing artifact retention policy may remove output files after seven days; expired previews/downloads report unavailable while conversation text remains. Download outputs that need long-term retention.
