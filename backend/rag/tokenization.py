from __future__ import annotations

import re
from typing import Any, Protocol, Self, runtime_checkable


@runtime_checkable
class TokenCounter(Protocol):
    """Count tokens without coupling chunking to a model tokenizer."""

    def count(self, text: str) -> int: ...


class HeuristicTokenCounter:
    """Deterministic, offline token estimate for mixed English and CJK text."""

    _TOKEN_PATTERN = re.compile(
        r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
        r"|[A-Za-z0-9]+(?:[_'’-][A-Za-z0-9]+)*"
        r"|[^\s]",
        re.UNICODE,
    )

    def count(self, text: str) -> int:
        if not text:
            return 0
        return sum(1 for _ in self._TOKEN_PATTERN.finditer(text))


class TransformersTokenCounter:
    """Adapter for an already-loaded Hugging Face-compatible tokenizer."""

    def __init__(self, tokenizer: Any) -> None:
        if not callable(getattr(tokenizer, "encode", None)):
            raise TypeError("tokenizer must provide an encode() method")
        self._tokenizer = tokenizer

    @classmethod
    def from_pretrained(
        cls,
        model_name_or_path: str,
        *,
        local_files_only: bool = False,
    ) -> Self:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            model_name_or_path,
            local_files_only=local_files_only,
        )
        return cls(tokenizer)

    def count(self, text: str) -> int:
        if not text:
            return 0
        token_ids = self._tokenizer.encode(text, add_special_tokens=False)
        return len(token_ids)


__all__ = ["HeuristicTokenCounter", "TokenCounter", "TransformersTokenCounter"]
