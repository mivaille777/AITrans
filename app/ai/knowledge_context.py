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


def _stage_diagnostics(normalized: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    compact = compact_knowledge_context(normalized, max_chars=max_chars)
    cards = list(normalized.get("cards", []))
    relations = list(normalized.get("relations", []))
    compact_cards = list(compact.get("cards", []))
    compact_relations = list(compact.get("relations", []))

    summaries_compacted = 0
    for index, compact_card in enumerate(compact_cards):
        if index >= len(cards):
            break
        if str(compact_card.get("summary", "")) != str(cards[index].get("summary", "")):
            summaries_compacted += 1

    used_chars = len(json.dumps(compact, ensure_ascii=False)) if compact else 0
    cards_included = len(compact_cards)
    relations_included = len(compact_relations)
    return {
        "max_chars": max(1_000, int(max_chars)),
        "used_chars": used_chars,
        "cards_included": cards_included,
        "relations_included": relations_included,
        "card_summaries_compacted": summaries_compacted,
        "cards_dropped": max(0, len(cards) - cards_included),
        "relations_dropped": max(0, len(relations) - relations_included),
        "truncated": (
            cards_included < len(cards)
            or relations_included < len(relations)
            or summaries_compacted > 0
        ),
    }


def knowledge_context_diagnostics(value: Any) -> dict[str, Any]:
    """Build a safe runtime summary without exposing card or relation content."""

    normalized = normalize_knowledge_context(value)
    if not normalized:
        return {}

    canvas = normalized.get("canvas") or {}
    cards = list(normalized.get("cards", []))
    relations = list(normalized.get("relations", []))
    document_ids = {
        str(card.get("document_id", "")).strip()
        for card in cards
        if str(card.get("document_id", "")).strip()
    }
    binding = "knowledge_canvas" if canvas.get("board_id") or canvas.get("board_name") else "knowledge_selection"

    return {
        "binding": binding,
        "canvas": {
            "board_id": _text(canvas.get("board_id"), 128),
            "board_name": _text(canvas.get("board_name"), 512),
            "scope_label": _text(canvas.get("scope_label"), 256),
        }
        if canvas
        else None,
        "attached": {
            "cards": len(cards),
            "relations": len(relations),
            "documents": len(document_ids),
        },
        "stages": {
            "planner": _stage_diagnostics(normalized, max_chars=7_000),
            "react": _stage_diagnostics(normalized, max_chars=8_000),
            "synthesis": _stage_diagnostics(normalized, max_chars=9_000),
        },
        "visibility": {
            "planner": True,
            "react": True,
            "synthesis": True,
        },
        "relation_trust": "organizational_context_not_factual_evidence",
    }


def knowledge_context_json(value: Any, *, max_chars: int = 10_000) -> str:
    compact = compact_knowledge_context(value, max_chars=max_chars)
    return json.dumps(compact, ensure_ascii=False) if compact else "{}"


__all__ = [
    "compact_knowledge_context",
    "knowledge_context_diagnostics",
    "knowledge_context_json",
    "normalize_knowledge_context",
]
