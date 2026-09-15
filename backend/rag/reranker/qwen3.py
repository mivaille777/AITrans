from __future__ import annotations

from threading import RLock
from typing import Any

from backend.rag.config import RagRerankerConfig


class Qwen3RerankerProvider:
    """Lazy runtime for Qwen3 reranker.

    Avoids accelerate meta-device dispatch because some Qwen3 reranker
    sequence-classification checkpoints fail during automatic device mapping.
    """

    def __init__(self, config: RagRerankerConfig | None = None) -> None:
        self.config = config or RagRerankerConfig()
        self._model = None
        self._tokenizer = None
        self._lock = RLock()

    def _load(self) -> None:
        if self._model is not None:
            return

        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        path = self.config.model_path.strip() or self.config.model
        device = self._resolve_device(torch)

        self._tokenizer = AutoTokenizer.from_pretrained(
            path,
            local_files_only=self.config.local_files_only,
        )

        self._model = AutoModelForSequenceClassification.from_pretrained(
            path,
            local_files_only=self.config.local_files_only,
            device_map=None,
            torch_dtype=torch.float16 if device == "cuda" else None,
        )

        self._model.to(device)
        self._model.eval()

    def _resolve_device(self, torch: Any) -> str:
        if self.config.device == "cuda" and torch.cuda.is_available():
            return "cuda"
        if self.config.device == "auto" and torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        with self._lock:
            self._load()
            import torch

            pairs = [(query, item) for item in documents]
            inputs = self._tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
            )
            device = next(self._model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}

            with torch.no_grad():
                scores = self._model(**inputs).logits.view(-1)

            return [float(x) for x in scores.cpu().tolist()]


__all__ = ["Qwen3RerankerProvider"]
