from __future__ import annotations

import re
import unicodedata
from itertools import pairwise

_CHEMICAL_FORMULA = (
    r"(?<![A-Za-z0-9])"
    r"(?=[A-Za-z0-9]*(?:\d|[a-z]))"
    r"(?:[A-Z][a-z]?\d*){2,}"
    r"(?:[·.]\d*(?:[A-Z][a-z]?\d*){2,})*"
    r"(?![A-Za-z0-9])"
)
_CHEMICAL_FORMULA_PATTERN = re.compile(_CHEMICAL_FORMULA)
_CHEMICAL_COMPONENT_PATTERN = re.compile(r"(?:[A-Z][a-z]?)+\d+|[A-Z][a-z]?\d*|\d+")
_TOKEN_PATTERN = re.compile(
    r"10\.\d{4,9}/[-._;()/:A-Za-z0-9\[\]+%]+"
    r"|(?i:(?:eq|fig|table|algorithm)\.?\s*\d+(?:\.\d+)*)"
    rf"|{_CHEMICAL_FORMULA}"
    r"|(?:[A-Za-z]\.){2,}[A-Za-z]?\.?"
    r"|[A-Za-z]+(?:[-_][A-Za-z0-9]+)+"
    r"|[A-Za-z]+\d+"
    r"|[A-Za-z]+"
    r"|\d+(?:\.\d+)*"
    r"|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+",
)
_CJK = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+$")


class SparseTokenizer:
    """Tokenize scientific identifiers, English words, and CJK n-grams."""

    VERSION = "scientific-v2"

    def tokenize(self, text: str) -> list[str]:
        normalized_text = unicodedata.normalize("NFKC", text)
        tokens: list[str] = []
        for match in _TOKEN_PATTERN.finditer(normalized_text):
            original_value = match.group(0)
            value = original_value.casefold()
            if value.startswith("10.") and "/" in value:
                value = self._trim_identifier_punctuation(value)
            if not value:
                continue
            if _CHEMICAL_FORMULA_PATTERN.fullmatch(original_value):
                tokens.append(value)
                tokens.extend(
                    component.group(0).casefold()
                    for component in _CHEMICAL_COMPONENT_PATTERN.finditer(
                        original_value
                    )
                    if component.group(0).casefold() != value
                )
                continue
            if _CJK.fullmatch(value):
                characters = list(value)
                tokens.extend(characters)
                tokens.extend(first + second for first, second in pairwise(characters))
            else:
                tokens.append(re.sub(r"\s+", " ", value))
        return tokens

    @staticmethod
    def _trim_identifier_punctuation(value: str) -> str:
        value = value.rstrip(".,;:!?")
        for opening, closing in (("(", ")"), ("[", "]")):
            while value.endswith(closing) and value.count(closing) > value.count(
                opening
            ):
                value = value[:-1]
        return value


__all__ = ["SparseTokenizer"]
