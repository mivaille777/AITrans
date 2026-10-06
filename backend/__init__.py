"""AITranslator WebReBuild backend package."""

import os

# Model workers share a desktop's RAM. OpenBLAS's default per-core workspaces
# can exhaust memory across processes; explicit user settings take precedence.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
