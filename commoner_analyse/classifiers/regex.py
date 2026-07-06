from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Pattern

from .base import BaseClassifier, ClassifyResult


@dataclass(frozen=True)
class TagRule:
    tag: str
    label: str
    patterns: tuple[Pattern[str], ...]
    weight: float = 1.0
    # exclude_patterns: a candidate match for this tag is *suppressed*
    # only if some exclude-pattern match spans the include match
    # entirely (i.e., ``[exclude_start, exclude_end] ⊇ [include_start,
    # include_end]``). Used for disambiguation: ``\bDRI\b`` (the agency)
    # excludes ``DRI\s+scheme`` (the unrelated banking initiative) for
    # *that specific occurrence*, leaving other DRI mentions in the
    # same document intact. Empty tuple = no exclusions, behaves like
    # v0.4.0.
    exclude_patterns: tuple[Pattern[str], ...] = field(default_factory=tuple)

    def count(self, text: str) -> int:
        if not self.exclude_patterns:
            # Fast path — preserves v0.4.0 semantics exactly.
            return sum(len(pattern.findall(text)) for pattern in self.patterns)
        # Pre-compute all exclude spans once. Containment check below.
        exclude_spans: list[tuple[int, int]] = []
        for ep in self.exclude_patterns:
            for em in ep.finditer(text):
                exclude_spans.append((em.start(), em.end()))
        n = 0
        for pattern in self.patterns:
            for m in pattern.finditer(text):
                start, end = m.start(), m.end()
                # Suppress this match iff some exclude span fully contains it.
                if not any(es <= start and ee >= end for es, ee in exclude_spans):
                    n += 1
        return n


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
                exclude_patterns=tuple(
                    re.compile(p, re.I | re.DOTALL)
                    for p in item.get("exclude_patterns", [])
                ),
            )
        )
    return tuple(rules)
