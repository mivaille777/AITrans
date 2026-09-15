"""Minimal DeepSeek API connectivity smoke test.

The smoke test exercises the shared DeepSeekClient instead of calling the
provider SDK directly. It performs a real network request and requires a
DeepSeek key already saved from Settings -> Cloud LLM in the Tauri desktop app.

Usage (PowerShell):
    python scripts/deepseek_smoke_test.py
"""

from __future__ import annotations

from app.ai.client import DeepSeekClient
from app.ai.errors import AIError


def main() -> int:
    client: DeepSeekClient | None = None
    try:
        client = DeepSeekClient()
        text = client.complete(
            system_prompt="You are a concise assistant.",
            user_prompt="Reply with exactly: DeepSeek API OK",
            temperature=0.0,
        )
    except AIError as exc:
        print(f"DeepSeek smoke test failed: {exc}")
        return 1
    finally:
        if client is not None:
            client.close()

    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
