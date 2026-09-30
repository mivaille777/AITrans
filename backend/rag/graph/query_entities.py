from __future__ import annotations

import re

from backend.rag.graph.models import normalize_alias


def query_entities(query: str, *, max_terms: int = 64) -> tuple[str, ...]:
    """Generate bounded literal alias probes; never invent expanded entities."""
    if max_terms <= 0:
        raise ValueError("graph query term budget must be positive")
    text = normalize_alias(query[:2048])
    words = re.findall(r"[\w./+-]+", text)[:64]
    terms = []
    for width in range(min(5, len(words)), 0, -1):
        for start in range(len(words) - width + 1):
            term = " ".join(words[start : start + width]).strip(".?")
            if term and term not in terms:
                terms.append(term)
            if len(terms) >= max_terms:
                return tuple(terms)
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        for width in range(min(8, len(run)), 1, -1):
            for start in range(len(run) - width + 1):
                term = run[start : start + width]
                if term not in terms:
                    terms.append(term)
                if len(terms) >= max_terms:
                    return tuple(terms)
    return tuple(terms)
