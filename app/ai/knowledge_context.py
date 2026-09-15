from __future__ import annotations

import json
from typing import Any

_MAX_CARDS = 60
_MAX_RELATIONS = 60


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _dict_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        return dict(dumped) if isinstance(dumped, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def normalize_knowledge_context(value: Any) -> dict[str, Any]:
    """Normalize the trusted Agent knowledge-context contract."""

    raw = _dict_value(value)
    if not raw:
        return {}

    canvas_raw = _dict_value(raw.get("canvas"))
    canvas = None
    if canvas_raw:
        board_id = _text(canvas_raw.get("board_id"), 128)
        board_name = _text(canvas_raw.get("board_name"), 512)
        scope_label = _text(canvas_raw.get("scope_label"), 256)
        if board_id or board_name or scope_label:
            canvas = {
                "board_id": board_id,
                "board_name": board_name,
                "scope_label": scope_label,
            }

    cards: list[dict[str, Any]] = []
    raw_cards = raw.get("cards", ())
    if isinstance(raw_cards, (list, tuple)):
        for raw_card in raw_cards[:_MAX_CARDS]:
            card = _dict_value(raw_card)
            if not card:
                continue
            item_id = _text(card.get("item_id"), 128)
            title = _text(card.get("title"), 1024)
            if not item_id and not title:
                continue
            cards.append(
                {
                    "item_id": item_id,
                    "item_type": _text(card.get("item_type"), 64),
                    "title": title,
                    "summary": _text(card.get("summary"), 8000),
                    "document_id": _text(card.get("document_id"), 256),
                }
            )

    relations: list[dict[str, Any]] = []
    raw_relations = raw.get("relations", ())
    if isinstance(raw_relations, (list, tuple)):
        for raw_relation in raw_relations[:_MAX_RELATIONS]:
            relation = _dict_value(raw_relation)
            if not relation:
                continue
            relation_id = _text(relation.get("relation_id"), 128)
            source_item_id = _text(relation.get("source_item_id"), 128)
            target_item_id = _text(relation.get("target_item_id"), 128)
            if not relation_id and not (source_item_id and target_item_id):
                continue
            confidence = relation.get("confidence")
            try:
                confidence_value = None if confidence is None else float(confidence)
            except (TypeError, ValueError):
                confidence_value = None
            relations.append(
                {
                    "relation_id": relation_id,
                    "source_item_id": source_item_id,
                    "source_title": _text(relation.get("source_title"), 1024),
                    "target_item_id": target_item_id,
                    "target_title": _text(relation.get("target_title"), 1024),
                    "relation_type": _text(relation.get("relation_type"), 128),
                    "label": _text(relation.get("label"), 1024),
                    "origin": _text(relation.get("origin"), 64),
                    "confidence": confidence_value,
                }
            )

    if canvas is None and not cards and not relations:
        return {}
    return {"canvas": canvas, "cards": cards, "relations": relations}


def compact_knowledge_context(value: Any, *, max_chars: int = 10_000) -> dict[str, Any]:
    """Return valid prompt JSON while preserving explicit relations first."""

    normalized = normalize_knowledge_context(value)
    if not normalized:
        return {}

    max_chars = max(1_000, int(max_chars))
    result: dict[str, Any] = {
        "canvas": normalized.get("canvas"),
        "cards": [],
        "relations": [],
    }

    relation_limit = max(1_000, int(max_chars * 0.65))
    for relation in normalized.get("relations", []):
        candidate = {**result, "relations": [*result["relations"], relation]}
        if len(json.dumps(candidate, ensure_ascii=False)) > relation_limit:
            break
        result["relations"].append(relation)

    for card in normalized.get("cards", []):
        compact_card = dict(card)
        compact_card["summary"] = _text(compact_card.get("summary"), 1200)
        candidate = {**result, "cards": [*result["cards"], compact_card]}
        if len(json.dumps(candidate, ensure_ascii=False)) > max_chars:
            break
        result["cards"].append(compact_card)

    return result


def knowledge_context_json(value: Any, *, max_chars: int = 10_000) -> str:
    compact = compact_knowledge_context(value, max_chars=max_chars)
    return json.dumps(compact, ensure_ascii=False) if compact else "{}"


__all__ = [
    "compact_knowledge_context",
    "knowledge_context_json",
    "normalize_knowledge_context",
]
