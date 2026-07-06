from __future__ import annotations

import math
import time
from typing import Any, Callable

from .base import BaseClassifier, ClassifyResult


class EmbeddingsClassifier(BaseClassifier):
    name = "embeddings"

    def __init__(
        self,
        *,
        embedding_model: str,
        anchors: dict[str, list[str]],
        threshold: float = 0.55,
        device: str = "auto",
        encoder: Callable[[list[str]], list[list[float]]] | None = None,
    ):
        if not anchors:
            raise ValueError("embeddings classifier requires non-empty anchors")
        self.embedding_model = embedding_model
        self.anchors = anchors
        self.threshold = float(threshold)
        self.device = device
        self._encoder = encoder
        self._model: Any = None
        self._anchor_vectors: dict[str, list[list[float]]] = {}

    def warmup(self) -> None:
        if not self._encoder:
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore
            except ImportError as exc:
                raise ImportError(
                    "Embeddings mode requires the optional extra: "
                    "pip install 'commoner-analyse[embeddings]'"
                ) from exc
            kwargs = {} if self.device == "auto" else {"device": self.device}
            self._model = SentenceTransformer(self.embedding_model, **kwargs)
            self._encoder = lambda texts: self._model.encode(texts, normalize_embeddings=True).tolist()
        self._anchor_vectors = {
            tag: self._encode(anchor_texts)
            for tag, anchor_texts in self.anchors.items()
        }

    def classify(self, *parts: str | None, **ctx: object) -> ClassifyResult:
        start = time.perf_counter()
        text = " ".join(part for part in parts if part).strip()
        if not text:
            return ClassifyResult(tags=[], classifier=self.name, model=self.embedding_model)
        if not self._anchor_vectors:
            self.warmup()
        text_vec = self._encode([text])[0]
        matches: dict[str, float] = {}
        for tag, anchor_vecs in self._anchor_vectors.items():
            best = max((_cosine(text_vec, anchor_vec) for anchor_vec in anchor_vecs), default=0.0)
            if best >= self.threshold:
                matches[tag] = best
        return ClassifyResult(
            tags=list(matches),
            matches=matches,
            score=sum(matches.values()),
            classifier=self.name,
            model=self.embedding_model,
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not self._encoder:
            self.warmup()
        assert self._encoder is not None
        return [[float(x) for x in row] for row in self._encoder(texts)]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)
