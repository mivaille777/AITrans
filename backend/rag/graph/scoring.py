from __future__ import annotations

from math import prod


def path_score(confidences: tuple[float, ...]) -> float:
    """Rank short supported paths; confidence is not a truth probability."""
    if any(not 0 <= value <= 1 for value in confidences):
        raise ValueError("graph confidence must be between zero and one")
    return prod(confidences) / len(confidences) if confidences else 0.25
