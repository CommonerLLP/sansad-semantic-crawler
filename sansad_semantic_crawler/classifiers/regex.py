from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Pattern

from .base import BaseClassifier, ClassifyResult


@dataclass(frozen=True)
class TagRule:
    tag: str
    label: str
    patterns: tuple[Pattern[str], ...]
    weight: float = 1.0

    def count(self, text: str) -> int:
        return sum(len(pattern.findall(text)) for pattern in self.patterns)


class RegexClassifier(BaseClassifier):
    name = "regex"

    def __init__(self, tag_rules: tuple[TagRule, ...], *, fallback_tag: str = "topic_match"):
        self.tag_rules = tag_rules
        self.fallback_tag = fallback_tag

    def classify(self, *parts: str | None, **ctx: object) -> ClassifyResult:
        start = time.perf_counter()
        blob = " ".join(part for part in parts if part)
        tags: list[str] = []
        matches: dict[str, float] = {}
        score = 0.0
        for rule in self.tag_rules:
            n = rule.count(blob)
            if n:
                tags.append(rule.tag)
                matches[rule.tag] = float(n)
                score += n * rule.weight
        if not tags and blob.strip():
            tags.append(self.fallback_tag)
        return ClassifyResult(
            tags=tags,
            matches=matches,
            score=score,
            classifier=self.name,
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )


def build_tag_rules(raw_rules: list[dict]) -> tuple[TagRule, ...]:
    rules = []
    for item in raw_rules:
        rules.append(
            TagRule(
                tag=item["tag"],
                label=item.get("label") or item["tag"].replace("_", " ").title(),
                patterns=tuple(re.compile(p, re.I | re.DOTALL) for p in item.get("patterns", [])),
                weight=float(item.get("weight", 1.0)),
            )
        )
    return tuple(rules)
