"""Start an offline, isolated localhost backend for Tools acceptance.

Only authored fixtures belong in this data directory. No production settings,
credential entries, or shipped defaults are written. Models must be cached.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8772)
    parser.add_argument("--frontend-origin", default="http://127.0.0.1:5187")
    args = parser.parse_args()
    data = root / "test-results" / "tools-live"
    data.mkdir(parents=True, exist_ok=True)
    os.environ["AITRANSLATOR_DATA_DIR"] = str(data)
    os.environ["AITRANS_FRONTEND_ORIGIN"] = args.frontend_origin
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    # Preserve the shipped baseline except optional generative/visual routes.
    lines = (root / "config/default.toml").read_text(encoding="utf-8").splitlines()
    section = ""
    for index, line in enumerate(lines):
        if line.startswith("["):
            section = line.strip()
        if section == "[rag]" and line.startswith("query_rewrite_enabled ="):
            lines[index] = "query_rewrite_enabled = false"
        if section in {
            "[rag.graph]", "[rag.advanced_parsing]", "[rag.visual_understanding]",
            "[rag.visual_retrieval]",
        } and line.startswith("enabled ="):
            lines[index] = "enabled = false"
    config = data / "acceptance-default.toml"
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    from app.infrastructure import settings

    settings.DEFAULT_CONFIG_PATH = config
    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    # Required for Windows model-worker multiprocessing; children must not serve.
    main()
