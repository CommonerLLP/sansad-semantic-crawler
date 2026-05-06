from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

from .base import BaseClassifier, ClassifyResult


class LLMClassifier(BaseClassifier):
    name = "llm"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        tag_definitions: dict[str, str],
        system_prompt: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
        timeout_s: float = 30.0,
        client: Any | None = None,
    ):
        if not tag_definitions:
            raise ValueError("llm classifier requires non-empty tag_definitions")
        self.endpoint = endpoint
        self.model = model
        self.tag_definitions = tag_definitions
        self.system_prompt = system_prompt or "Tag Indian parliamentary questions against the provided taxonomy."
        self.api_key = api_key or "local"
        self.temperature = float(temperature)
        self.timeout_s = float(timeout_s)
        self.client = client

    def warmup(self) -> None:
        return None

    def classify(self, *parts: str | None, **ctx: object) -> ClassifyResult:
        start = time.perf_counter()
        text = " ".join(part for part in parts if part).strip()
        if not text:
            return ClassifyResult(tags=[], classifier=self.name, model=self.model)
        self.warmup()
        prompt = {
            "task": "Return JSON only. Choose zero or more tag keys that apply to the text.",
            "tag_definitions": self.tag_definitions,
            "text": text,
            "schema": {
                "tags": ["tag_key"],
                "confidence": {"tag_key": 0.0},
                "reasoning": "brief explanation",
            },
        }
        try:
            if self.client is not None:
                response = self.client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                )
                content = response.choices[0].message.content or "{}"
            else:
                payload = {
                    "model": self.model,
                    "temperature": self.temperature,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                }
                content = _chat_completions_post(
                    self.endpoint,
                    payload,
                    api_key=self.api_key,
                    timeout_s=self.timeout_s,
                )
            try:
                parsed = _parse_jsonish(content)
            except Exception as exc:  # noqa: BLE001
                tags = _fallback_tags(content, self.tag_definitions)
                return ClassifyResult(
                    tags=tags,
                    matches={tag: 1.0 for tag in tags},
                    score=float(len(tags)),
                    explain=f"LLM returned non-JSON output: {exc}",
                    classifier=self.name,
                    model=self.model,
                    elapsed_ms=(time.perf_counter() - start) * 1000,
                )
            allowed = set(self.tag_definitions)
            tags = [tag for tag in parsed.get("tags", []) if tag in allowed]
            confidence = parsed.get("confidence") or {}
            matches = {tag: float(confidence.get(tag, 1.0)) for tag in tags}
            return ClassifyResult(
                tags=tags,
                matches=matches,
                score=sum(matches.values()),
                explain=parsed.get("reasoning"),
                classifier=self.name,
                model=self.model,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:  # noqa: BLE001
            tags = _fallback_tags(str(exc), self.tag_definitions)
            return ClassifyResult(
                tags=tags,
                matches={tag: 1.0 for tag in tags},
                score=float(len(tags)),
                explain=f"LLM classification failed: {exc}",
                classifier=self.name,
                model=self.model,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )


def _chat_completions_post(endpoint: str, payload: dict[str, Any], *, api_key: str, timeout_s: float) -> str:
    base = endpoint.rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    key = os.environ.get(api_key[4:]) if api_key.startswith("env:") else api_key
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Chat-completions request failed: {exc}") from exc
    data = json.loads(raw)
    return data["choices"][0]["message"].get("content") or "{}"


def _parse_jsonish(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _fallback_tags(content: str, tag_definitions: dict[str, str]) -> list[str]:
    found = []
    for tag in tag_definitions:
        if re.search(rf"\b{re.escape(tag)}\b", content):
            found.append(tag)
    return found
