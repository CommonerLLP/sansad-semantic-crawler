from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Pattern


@dataclass(frozen=True)
class TagRule:
    tag: str
    label: str
    patterns: tuple[Pattern[str], ...]
    weight: float = 1.0

    def count(self, text: str) -> int:
        return sum(len(pattern.findall(text)) for pattern in self.patterns)


@dataclass(frozen=True)
class TopicProfile:
    name: str
    description: str
    search_groups: dict[str, list[str]]
    lok_sabha_ministries: list[str]
    rajya_sabha_ministry_likes: list[str]
    tag_rules: tuple[TagRule, ...]
    fallback_tag: str = "topic_match"

    @property
    def tag_labels(self) -> dict[str, str]:
        labels = {rule.tag: rule.label for rule in self.tag_rules}
        labels.setdefault(self.fallback_tag, self.fallback_tag.replace("_", " ").title())
        return labels

    def searches(self, max_buckets: int | None = None) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for group, queries in self.search_groups.items():
            pairs.extend((group, query) for query in queries)
        return pairs[:max_buckets] if max_buckets is not None else pairs

    def classify(self, *parts: str | None) -> dict:
        blob = " ".join(part for part in parts if part)
        tags: list[str] = []
        matches: dict[str, int] = {}
        score = 0.0
        for rule in self.tag_rules:
            n = rule.count(blob)
            if n:
                tags.append(rule.tag)
                matches[rule.tag] = n
                score += n * rule.weight
        if not tags and blob.strip():
            tags.append(self.fallback_tag)
        return {
            "tags": sorted(set(tags)),
            "matches": matches,
            "score": round(score, 3),
        }


def load_topic(path: str | Path) -> TopicProfile:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = []
    for item in raw.get("tag_rules", []):
        rules.append(
            TagRule(
                tag=item["tag"],
                label=item.get("label") or item["tag"].replace("_", " ").title(),
                patterns=tuple(re.compile(p, re.I | re.DOTALL) for p in item.get("patterns", [])),
                weight=float(item.get("weight", 1.0)),
            )
        )
    return TopicProfile(
        name=raw["name"],
        description=raw.get("description", ""),
        search_groups={k: list(v) for k, v in raw.get("search_groups", {}).items()},
        lok_sabha_ministries=list(raw.get("lok_sabha_ministries", [])),
        rajya_sabha_ministry_likes=list(raw.get("rajya_sabha_ministry_likes", [])),
        tag_rules=tuple(rules),
        fallback_tag=raw.get("fallback_tag", "topic_match"),
    )

