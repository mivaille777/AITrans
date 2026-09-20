"""Manual real-network smoke test for the current Youdao WebFanyi provider.

Run from repository root:
    python scripts/manual/youdao_translation_smoke_test.py
    python scripts/manual/youdao_translation_smoke_test.py "Hello world" --source en --target zh-CN

The provider is invoked directly so TranslationCache cannot hide a real
network/protocol failure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.models.translation import TranslationRequest
from app.translation.youdao_web_provider import YoudaoWebTranslationProvider


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("text", nargs="?", default="Hello world")
    parser.add_argument("--source", default="en")
    parser.add_argument("--target", default="zh-CN")
    args = parser.parse_args()

    provider = YoudaoWebTranslationProvider()
    try:
        print(f"provider = {provider.name}")
        print(f"endpoint = {provider.endpoint}")
        print(f"key_endpoint = {provider.key_endpoint}")
        result = provider.translate(
            TranslationRequest(
                source_text=args.text,
                source_language=args.source,
                target_language=args.target,
                request_id=1,
            )
        )
        print(f"translated_text = {result.translated_text}")
        print(f"source_language = {result.source_language}")
        print(f"target_language = {result.target_language}")
        return 0
    except Exception as exc:
        print(f"error_type = {type(exc).__name__}")
        print(f"error = {exc}")
        raise
    finally:
        provider.close()


if __name__ == "__main__":
    raise SystemExit(main())
