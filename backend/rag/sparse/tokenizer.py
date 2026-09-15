from __future__ import annotations

import re
from itertools import pairwise

_TOKEN_PATTERN = re.compile(
    r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+"
    r"|(?:eq|fig|table|algorithm)\.?\s*\d+(?:\.\d+)*"
    r"|[A-Za-z]+(?:[-_][A-Za-z0-9]+)+"
    r"|[A-Za-z]+\d+"
    r"|[A-Za-z]+"
    r"|\d+(?:\.\d+)*"
    r"|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+",
    re.IGNORECASE,
)
_CJK = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+$")


class SparseTokenizer:
    """Tokenize scientific identifiers, English words, and CJK n-grams."""

    def tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        for match in _TOKEN_PATTERN.finditer(text):
            value = match.group(0).strip().lower()
            if _CJK.fullmatch(value):
                characters = list(value)
                tokens.extend(characters)
                tokens.extend(first + second for first, second in pairwise(characters))
            else:
                tokens.append(re.sub(r"\s+", " ", value))
        return tokens


__all__ = ["SparseTokenizer"]
