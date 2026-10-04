from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np


class BM25Index:
    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("BM25 requires k1 > 0 and 0 <= b <= 1")
        self.k1 = k1
        self.b = b
        self._postings: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._document_ids: list[str] = []
        self._lengths = np.empty(0, dtype=np.float64)
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

        self._document_ids = list(lengths)
        positions = {document_id: index for index, document_id in enumerate(self._document_ids)}
        self._lengths = np.fromiter(lengths.values(), dtype=np.float64)
        self._postings = {
            term: (np.fromiter((positions[item] for item in values), dtype=np.intp),
                   np.fromiter(values.values(), dtype=np.float64))
            for term, values in postings.items()
        }
        self._document_count = len(lengths)
        self._average_length = (
            sum(lengths.values()) / self._document_count if lengths else 0.0
        )

    def score(self, query_tokens: list[str]) -> dict[str, float]:
        if not query_tokens or not self._document_count:
            return {}
        scores = np.zeros(self._document_count, dtype=np.float64)
        normalization = self.k1 * (1 - self.b + self.b * self._lengths / max(self._average_length, 1))
        for term in dict.fromkeys(query_tokens):
            postings = self._postings.get(term)
            if postings is None:
                continue
            rows, frequencies = postings
            document_frequency = len(rows)
            inverse_frequency = math.log(
                1
                + (self._document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            scores[rows] += inverse_frequency * (
                frequencies * (self.k1 + 1) / (frequencies + normalization[rows])
            )
        return {self._document_ids[index]: float(scores[index]) for index in np.flatnonzero(scores)}


__all__ = ["BM25Index"]
