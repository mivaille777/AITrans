"""Validation and cleanup for model-generated AI text.

The guard is deliberately provider-independent. It accepts plain text from an
LLM, removes harmless presentation wrappers, and rejects outputs that look like
request payload echoes or otherwise fail the application contract.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from app.ai.models import AITextAction

JSON_PAYLOAD_KEYS = frozenset(
    {
        "task",
        "source_language",
        "target_language",
        "language",
        "style",
        "style_instruction",
        "source_text",
    }
)
JSON_RESULT_KEYS = (
    "translated_text",
    "translation",
    "polished_text",
    "output_text",
    "output",
    "result",
    "text",
)

_PREFIX_RE = re.compile(
    r"^(?:translation|translated text|polished text|polished version|result|output)\s*:\s*",
    re.IGNORECASE,
)
_FENCE_OPEN_RE = re.compile(r"^```(?:text|plain|plaintext|markdown|json)?\s*", re.IGNORECASE)
_FENCE_CLOSE_RE = re.compile(r"\s*```$", re.IGNORECASE)
_CITATION_RE = re.compile(r"\[(?:\d+(?:\s*[-,]\s*\d+)*)\]")
_NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)?%?")
_UNIT_RE = re.compile(
    r"(?<!\w)(?:ms|s|kg|g|mg|km|cm|mm|°c|k|pa|kpa|mpa|hz|khz|mhz|j|w|kw|v|mv|a|ma)(?!\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class OutputValidation:
    """Normalized model output plus an optional rejection reason."""

    text: str
    valid: bool
    reason: str = ""


def normalize_model_output(content: object) -> str:
    """Remove harmless wrappers while preserving the actual generated text."""

    if not isinstance(content, str):
        return ""

    text = content.strip()
    if not text:
        return ""

    text = _FENCE_OPEN_RE.sub("", text)
    text = _FENCE_CLOSE_RE.sub("", text).strip()

    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            for key in JSON_RESULT_KEYS:
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return _PREFIX_RE.sub("", value.strip()).strip()

    return _PREFIX_RE.sub("", text).strip()


def _json_payload_echo(text: str) -> bool:
    if not (text.startswith("{") and text.endswith("}")):
        return False
    try:
        data = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    keys = {str(key) for key in data}
    return "source_text" in keys and bool(keys & JSON_PAYLOAD_KEYS)


def _normalized_for_comparison(text: str) -> str:
    return " ".join(text.split()).casefold()


def _missing_protected_tokens(source_text: str, output_text: str) -> str:
    for reason, pattern in (
        ("citation_mapping_changed", _CITATION_RE),
        ("numeric_value_changed", _NUMBER_RE),
        ("unit_mapping_changed", _UNIT_RE),
    ):
        source = Counter(item.casefold() for item in pattern.findall(source_text))
        output = Counter(item.casefold() for item in pattern.findall(output_text))
        if any(output[token] < count for token, count in source.items()):
            return reason
    return ""


def validate_model_output(
    content: object,
    *,
    source_text: str,
    action: AITextAction,
) -> OutputValidation:
    """Validate a raw model response before it reaches the Overlay."""

    raw = content.strip() if isinstance(content, str) else ""
    if not raw:
        return OutputValidation("", False, "empty_output")

    # Check the raw response before JSON result extraction. A request payload
    # echo such as {task, source_text, ...} must never be accepted as output.
    if _json_payload_echo(raw):
        return OutputValidation("", False, "request_payload_echo")

    normalized = normalize_model_output(raw)
    if not normalized:
        return OutputValidation("", False, "empty_output")

    source_cmp = _normalized_for_comparison(source_text)
    output_cmp = _normalized_for_comparison(normalized)
    if source_cmp and output_cmp == source_cmp:
        # An unchanged source is always suspicious for translation. For polish
        # it is also treated as a failed generation so the strict retry gets a
        # chance to improve the text rather than silently doing nothing.
        return OutputValidation("", False, "unchanged_source")

    if action is AITextAction.TRANSLATE and source_cmp:
        # Reject a payload-like wrapper that survived because it was malformed
        # JSON but still contains the complete source plus request field names.
        lowered = raw.casefold()
        if source_cmp in _normalized_for_comparison(raw) and any(
            f'"{field}"' in lowered for field in ("task", "source_text", "target_language")
        ):
            return OutputValidation("", False, "request_payload_echo")

    protected_failure = _missing_protected_tokens(source_text, normalized)
    if protected_failure:
        return OutputValidation("", False, protected_failure)

    return OutputValidation(normalized, True)


__all__ = [
    "OutputValidation",
    "normalize_model_output",
    "validate_model_output",
]
