from __future__ import annotations

from typing import Any

from .base import Classifier, ClassifyResult
from .embeddings import EmbeddingsClassifier
from .ensemble import EnsembleClassifier
from .llm import LLMClassifier
from .regex import RegexClassifier, TagRule


def build_classifier(
    config: dict[str, Any] | None,
    *,
    tag_rules: tuple[TagRule, ...],
    fallback_tag: str,
    override: str | None = None,
) -> Classifier:
    raw = dict(config or {})
    mode = override or raw.get("mode") or "regex"
    if mode == "regex":
        return RegexClassifier(tag_rules, fallback_tag=fallback_tag)
    if mode == "embeddings":
        return EmbeddingsClassifier(
            embedding_model=raw.get("embedding_model", "BAAI/bge-m3"),
            anchors={k: list(v) for k, v in raw.get("anchors", {}).items()},
            threshold=float(raw.get("threshold", 0.55)),
            device=raw.get("device", "auto"),
        )
    if mode == "llm":
        return LLMClassifier(
            endpoint=raw.get("endpoint", "http://localhost:11434/v1"),
            model=raw.get("model", "Qwen/Qwen2.5-7B-Instruct"),
            tag_definitions={k: str(v) for k, v in raw.get("tag_definitions", {}).items()},
            system_prompt=raw.get("system_prompt"),
            api_key=raw.get("api_key"),
            temperature=float(raw.get("temperature", 0.0)),
            timeout_s=float(raw.get("timeout_s", 30.0)),
        )
    if mode == "ensemble":
        members = [
            build_classifier(member, tag_rules=tag_rules, fallback_tag=fallback_tag)
            for member in raw.get("members", [])
        ]
        return EnsembleClassifier(
            members,
            combine=raw.get("combine", "union"),
            weights={k: float(v) for k, v in raw.get("weights", {}).items()},
        )
    raise ValueError(f"Unknown classifier mode: {mode}")


__all__ = [
    "Classifier",
    "ClassifyResult",
    "EmbeddingsClassifier",
    "EnsembleClassifier",
    "LLMClassifier",
    "RegexClassifier",
    "TagRule",
    "build_classifier",
]
