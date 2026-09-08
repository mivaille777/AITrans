from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RelationSuggestion:
    source: str
    target: str
    relation: str
    confidence: float


def suggest_relations(nodes: list[dict]) -> list[dict]:
    """Lightweight relation proposal layer.

    This is intentionally deterministic at this stage. The later Agent Runtime
    phase can replace it with embedding retrieval plus LLM reasoning.
    """
    suggestions: list[dict] = []
    for index, source in enumerate(nodes):
        for target in nodes[index + 1 :]:
            if source.get("type") == "paper" and target.get("type") == "concept":
                suggestions.append(
                    {
                        "source": source["id"],
                        "target": target["id"],
                        "relation": "supports",
                        "confidence": 0.72,
                    }
                )
    return suggestions
