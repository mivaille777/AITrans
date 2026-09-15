from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def runtime_smoke_test() -> int:
    import qdrant_client
    import sentence_transformers
    import transformers

    from backend.main import create_app
    from backend.rag.model_manager import ModelManager

    app = create_app()
    manager = ModelManager()
    print(
        json.dumps(
            {
                "status": "ok",
                "app": app.title,
                "models_root": str(manager.models_root),
                "runtime": {
                    "qdrant-client": _package_version("qdrant-client"),
                    "sentence-transformers": _package_version("sentence-transformers"),
                    "transformers": _package_version("transformers"),
                },
                "imports": [
                    qdrant_client.__name__,
                    sentence_transformers.__name__,
                    transformers.__name__,
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AITrans FastAPI backend sidecar")
    parser.add_argument(
        "--runtime-smoke-test",
        action="store_true",
        help="verify packaged local RAG runtime imports and exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(None if argv is None else list(argv))
    if args.runtime_smoke_test:
        return runtime_smoke_test()
    from backend.main import main as backend_main

    backend_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
