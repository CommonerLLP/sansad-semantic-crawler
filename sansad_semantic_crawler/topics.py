from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .classifiers import Classifier, TagRule, build_classifier
from .classifiers.regex import build_tag_rules


@dataclass(frozen=True)
class TopicProfile:
    name: str
    description: str
    search_groups: dict[str, list[str]]
    lok_sabha_ministries: list[str]
    rajya_sabha_ministry_likes: list[str]
    tag_rules: tuple[TagRule, ...]
    classifier: Classifier
    classifier_config: dict[str, Any]
    fallback_tag: str = "topic_match"

    @property
    def tag_labels(self) -> dict[str, str]:
        labels = {rule.tag: rule.label for rule in self.tag_rules}
        for tag in _classifier_tags(self.classifier_config):
            labels.setdefault(tag, tag.replace("_", " ").title())
        labels.setdefault(self.fallback_tag, self.fallback_tag.replace("_", " ").title())
        return labels

    def searches(self, max_buckets: int | None = None) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for group, queries in self.search_groups.items():
            pairs.extend((group, query) for query in queries)
        return pairs[:max_buckets] if max_buckets is not None else pairs

    def classify(self, *parts: str | None) -> dict:
        return self.classifier.classify(*parts).to_dict()


def load_topic(path: str | Path, *, classifier_override: str | None = None) -> TopicProfile:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    tag_rules = build_tag_rules(raw.get("tag_rules", []))
    fallback_tag = raw.get("fallback_tag", "topic_match")
    classifier_config = dict(raw.get("classifier") or {})
    classifier = build_classifier(
        classifier_config,
        tag_rules=tag_rules,
        fallback_tag=fallback_tag,
        override=classifier_override,
    )
    return TopicProfile(
        name=raw["name"],
        description=raw.get("description", ""),
        search_groups={k: list(v) for k, v in raw.get("search_groups", {}).items()},
        lok_sabha_ministries=list(raw.get("lok_sabha_ministries", [])),
        rajya_sabha_ministry_likes=list(raw.get("rajya_sabha_ministry_likes", [])),
        tag_rules=tag_rules,
        classifier=classifier,
        classifier_config=classifier_config,
        fallback_tag=fallback_tag,
    )


def _classifier_tags(config: dict[str, Any]) -> set[str]:
    tags = set((config.get("anchors") or {}).keys())
    tags.update((config.get("tag_definitions") or {}).keys())
    for member in config.get("members", []):
        if isinstance(member, dict):
            tags.update(_classifier_tags(member))
    return tags
