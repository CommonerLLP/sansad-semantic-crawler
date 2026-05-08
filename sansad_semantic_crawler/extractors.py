from __future__ import annotations

import json
import re
from typing import Any

from .classifiers.llm import LLMClassifier


class CompositionExtractor:
    """Extracts committee member lists from unstructured text using an LLM."""

    def __init__(self, classifier_config: dict[str, Any]):
        self.config = classifier_config
        # We reuse the LLM configuration from the classifier (endpoint, model, etc.)
        self.llm = None
        if classifier_config.get("mode") == "llm":
            self.llm = LLMClassifier(
                endpoint=classifier_config["endpoint"],
                model=classifier_config["model"],
                tag_definitions={"member": "A person listed as a member"},  # Dummy tags
                system_prompt="You are an expert at parsing Indian parliamentary committee rosters.",
                api_key=classifier_config.get("api_key"),
                temperature=0.0,
            )
        elif classifier_config.get("mode") == "ensemble":
            # Find the LLM member in the ensemble
            for member in classifier_config.get("members", []):
                if member.get("mode") == "llm":
                    self.llm = LLMClassifier(
                        endpoint=member["endpoint"],
                        model=member["model"],
                        tag_definitions={"member": "A person listed as a member"},
                        system_prompt="You are an expert at parsing Indian parliamentary committee rosters.",
                        api_key=member.get("api_key"),
                        temperature=0.0,
                    )
                    break

    def extract(self, text: str) -> list[dict[str, str]]:
        """Interpret the text and return a list of members with house/role info."""
        if not text.strip():
            return []

        # 1. Try Regex first (Fast, free, reliable for standard layouts)
        members = self._extract_via_regex(text)
        if members:
            return members

        # 2. Fallback to LLM (Intelligent but expensive/slow)
        if not self.llm:
            return []

        from .classifiers.llm import _chat_completions_post, _parse_jsonish

        prompt = {
            "task": "Extract the list of committee members from the following text.",
            "instructions": [
                "Return a JSON object with a 'members' key containing a list of objects.",
                "Each member object should have: 'name', 'house' (Lok Sabha or Rajya Sabha), and 'role' (Chairperson, Member, etc.).",
                "Only include the names listed in the roster sections.",
            ],
            "text": text[:15000],
            "schema": {"members": [{"name": "...", "house": "...", "role": "..."}]},
        }

        try:
            payload = {
                "model": self.llm.model,
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": self.llm.system_prompt},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
            }
            content = _chat_completions_post(
                self.llm.endpoint,
                payload,
                api_key=self.llm.api_key,
                timeout_s=self.llm.timeout_s,
            )
            parsed = _parse_jsonish(content)
            return parsed.get("members", [])
        except Exception:  # noqa: BLE001
            return []

    def _extract_via_regex(self, text: str) -> list[dict[str, str]]:
        """Parse standard numbered member lists."""
        members = []
        current_house = None
        
        # Look for the composition section (various heading styles)
        section_match = re.search(r"(?:COMPOSITION|CONSTITUTED\s+W\.?E\.?F\.?)(.*?)(?=\n\s*\d+\.\s+INTRODUCTION|\n\s*REPORT|\n\s*CONTENTS|\f|\Z)", text, re.S | re.I)
        content = section_match.group(1) if section_match else text[:20000]
        # print(f"DEBUG: Found section content length: {len(content)}")

        # Lines like "RAJYA SABHA" or "LOK SABHA" set the context
        lines = content.splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Update house context
            if "RAJYA SABHA" in line.upper():
                current_house = "Rajya Sabha"
                continue
            if "LOK SABHA" in line.upper():
                current_house = "Lok Sabha"
                continue
            
            # Match "1. Shri Name role" or "1. Shri Name - role"
            # Using ¾ or - or — or just a big gap
            m = re.match(r"^(\d+)\.?\s+(.*?)(?:\s+[¾\-\u2013\u2014]\s+|\s{3,})(.*)?$", line)
            if m:
                name = m.group(2).strip()
                role = m.group(3).strip() if m.group(3) else "Member"
            else:
                # Try a simpler match for members without a specific role suffix
                m = re.match(r"^(\d+)\.?\s+(.*)$", line)
                if m:
                    name = m.group(2).strip()
                    role = "Member"
                else:
                    continue

            # If name contains only symbols or hashtags, skip
            if not re.search(r"[a-z]", name, re.I):
                continue
            members.append({
                "name": name,
                "house": current_house or "Unknown",
                "role": role
            })
        
        return members
