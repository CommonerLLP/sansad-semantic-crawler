from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ClassifyResult:
    tags: list[str]
    matches: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    explain: str | None = None
    model: str | None = None
    classifier: str | None = None
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        out = {
            "tags": sorted(set(self.tags)),
            "matches": self.matches,
            "score": round(float(self.score), 3),
        }
        if self.explain:
            out["explain"] = self.explain
        if self.model:
            out["model"] = self.model
        if self.classifier:
            out["classifier"] = self.classifier
        if self.elapsed_ms:
            out["elapsed_ms"] = round(float(self.elapsed_ms), 3)
        return out


@runtime_checkable
class Classifier(Protocol):
    name: str

    def classify(self, *parts: str | None, **ctx: object) -> ClassifyResult:
        ...

    def warmup(self) -> None:
        ...

    def close(self) -> None:
        ...


class BaseClassifier:
    name = "base"

    def warmup(self) -> None:
        return None

    def close(self) -> None:
        return None
