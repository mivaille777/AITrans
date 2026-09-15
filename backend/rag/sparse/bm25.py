from __future__ import annotations

import math
from collections import Counter, defaultdict


class BM25Index:
    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("BM25 requires k1 > 0 and 0 <= b <= 1")
        self.k1 = k1
        self.b = b
        self._documents: dict[str, Counter[str]] = {}
        self._lengths: dict[str, int] = {}
        self._document_frequency: Counter[str] = Counter()

    def rebuild(self, tokenized_documents: dict[str, list[str]]) -> None:
        self._documents = {
            document_id: Counter(tokens)
            for document_id, tokens in tokenized_documents.items()
        }
        self._lengths = {
            document_id: sum(frequencies.values())
            for document_id, frequencies in self._documents.items()
        }
        frequency: Counter[str] = Counter()
        for frequencies in self._documents.values():
            frequency.update(frequencies.keys())
        self._document_frequency = frequency

    def score(self, query_tokens: list[str]) -> dict[str, float]:
        if not query_tokens or not self._documents:
            return {}
        average_length = sum(self._lengths.values()) / len(self._lengths)
        scores: defaultdict[str, float] = defaultdict(float)
        document_count = len(self._documents)
        for term in dict.fromkeys(query_tokens):
            document_frequency = self._document_frequency.get(term, 0)
            if document_frequency == 0:
                continue
            inverse_frequency = math.log(
                1
                + (document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            for document_id, frequencies in self._documents.items():
                term_frequency = frequencies.get(term, 0)
                if term_frequency == 0:
                    continue
                length = self._lengths[document_id]
                denominator = term_frequency + self.k1 * (
                    1 - self.b + self.b * length / max(average_length, 1)
                )
                scores[document_id] += inverse_frequency * (
                    term_frequency * (self.k1 + 1) / denominator
                )
        return dict(scores)


__all__ = ["BM25Index"]
