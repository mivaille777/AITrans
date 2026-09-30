from __future__ import annotations

import math
from collections import Counter, defaultdict


class BM25Index:
    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("BM25 requires k1 > 0 and 0 <= b <= 1")
        self.k1 = k1
        self.b = b
        self._postings: dict[str, dict[str, int]] = {}
        self._lengths: dict[str, int] = {}
        self._document_count = 0
        self._average_length = 0.0

    def rebuild(self, tokenized_documents: dict[str, list[str]]) -> None:
        postings: defaultdict[str, dict[str, int]] = defaultdict(dict)
        lengths: dict[str, int] = {}
        for document_id, tokens in tokenized_documents.items():
            frequencies = Counter(tokens)
            lengths[document_id] = sum(frequencies.values())
            for term, term_frequency in frequencies.items():
                postings[term][document_id] = term_frequency

        self._postings = dict(postings)
        self._lengths = lengths
        self._document_count = len(lengths)
        self._average_length = (
            sum(lengths.values()) / self._document_count if lengths else 0.0
        )

    def score(self, query_tokens: list[str]) -> dict[str, float]:
        if not query_tokens or not self._document_count:
            return {}
        scores: defaultdict[str, float] = defaultdict(float)
        for term in dict.fromkeys(query_tokens):
            postings = self._postings.get(term)
            if not postings:
                continue
            document_frequency = len(postings)
            inverse_frequency = math.log(
                1
                + (self._document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            for document_id, term_frequency in postings.items():
                length = self._lengths[document_id]
                denominator = term_frequency + self.k1 * (
                    1 - self.b + self.b * length / max(self._average_length, 1)
                )
                scores[document_id] += inverse_frequency * (
                    term_frequency * (self.k1 + 1) / denominator
                )
        return dict(scores)


__all__ = ["BM25Index"]
