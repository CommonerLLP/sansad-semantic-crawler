from __future__ import annotations

import time

from .base import BaseClassifier, Classifier, ClassifyResult


class EnsembleClassifier(BaseClassifier):
    name = "ensemble"

    def __init__(
        self,
        members: list[Classifier],
        *,
        combine: str = "union",
        weights: dict[str, float] | None = None,
    ):
        if not members:
            raise ValueError("ensemble classifier requires at least one member")
        if combine not in {"union", "intersection", "weighted"}:
            raise ValueError("ensemble combine must be one of: union, intersection, weighted")
        self.members = members
        self.combine = combine
        self.weights = weights or {}

    def warmup(self) -> None:
        for member in self.members:
            member.warmup()

    def close(self) -> None:
        for member in self.members:
            member.close()

    def classify(self, *parts: str | None, **ctx: object) -> ClassifyResult:
        start = time.perf_counter()
        results = [member.classify(*parts, **ctx) for member in self.members]
        tag_sets = [set(result.tags) for result in results]
        if self.combine == "intersection":
            tags = sorted(set.intersection(*tag_sets)) if tag_sets else []
        else:
            tags = sorted(set.union(*tag_sets)) if tag_sets else []

        matches: dict[str, float] = {}
        for result in results:
            weight = self.weights.get(result.classifier or "", 1.0)
            for tag, value in result.matches.items():
                if tag in tags:
                    matches[tag] = matches.get(tag, 0.0) + float(value) * weight
        if self.combine == "weighted":
            tags = sorted(matches)
        explain = "; ".join(
            f"{result.classifier or 'classifier'}={','.join(result.tags) or 'none'}"
            for result in results
        )
        return ClassifyResult(
            tags=tags,
            matches=matches,
            score=sum(matches.values()),
            explain=explain,
            classifier=self.name,
            model="+".join(filter(None, (result.model for result in results))) or None,
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )
