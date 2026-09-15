"""Explicit real-network smoke test for the Google browser-web provider.

The script bypasses TranslationCache and FastAPI so it tests only the provider
and its browser-style GTX request contract against ``translate.google.com``.

Run from the repository root:
    python scripts/manual/google_translation_smoke_test.py
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.models.translation import TranslationRequest
from app.translation.google_web_provider import GoogleWebTranslationProvider

DEFAULT_TEXT = "The proposed method uses a Gaussian process to guide local search."


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Make one explicit browser-style Google Translate web request."
    )
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--source-language", default="en")
    parser.add_argument("--target-language", default="zh-CN")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(None if argv is None else list(argv))
    request = TranslationRequest(
        source_text=arguments.text,
        source_language=arguments.source_language,
        target_language=arguments.target_language,
    )

    provider = GoogleWebTranslationProvider()
    try:
        print(f"provider = {provider.name}")
        print(f"endpoint = {provider.endpoint}")
        print(f"tk = {provider._token(request.source_text)}")
        result = provider.translate(request)
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
