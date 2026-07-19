"""Grounded committee-roster extraction from committee-report text.

The LLM (via langextract, optional ``llm`` extra) only spots person
entities and vacancy markers with char-level spans. Everything structural
is derived deterministically afterwards: house/section comes from span
position relative to section headers, never from LLM attributes — small
local models flip section labels mid-list while their spans stay exact.
Ungrounded extractions (``char_interval is None``) are dropped and
counted; that channel is where few-shot leakage and hallucinated names
arrive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

COMPOSITION_HEADING = "COMPOSITION OF THE COMMITTEE"
SECTION_HEADERS = ("RAJYA SABHA", "LOK SABHA", "SECRETARIAT")

# Roster entries universally carry an honorific; extractions without one
# are window-tail junk (page furniture, article references), not people.
_HONORIFIC_RE = re.compile(
    r"^(Shri|Shrimati|Smt|Dr|Prof|Ms|Mr|Adv|Km|Kum|Sardar|Justice)\b\.?", re.I
)

_PROMPT = """\
Extract every person listed in this parliamentary committee composition.
Use the exact name text as it appears (do not fix spacing or spelling).
Extract vacancy markers ('#' entries or the word 'Vacant') as class
'vacancy'. Do not invent people who are not in the text."""

_EXAMPLE_TEXT = (
    "COMMITTEE ON EXAMPLE AFFAIRS\n1.\nShri Example Chairperson\nRAJYA SABHA\n"
    "2.\nDr.GluedNameExample\n3.\nVacant\nLOK SABHA\n4.\nSmt. Lok Member\n"
)
_EXAMPLE_ENTITIES = (
    ("member", "Shri Example Chairperson"),
    ("member", "Dr.GluedNameExample"),
    ("vacancy", "Vacant"),
    ("member", "Smt. Lok Member"),
)


@dataclass
class RosterMember:
    name: str
    start: int
    end: int
    section: str | None


@dataclass
class RosterResult:
    members: list[RosterMember] = field(default_factory=list)
    vacancies: int = 0
    dropped_ungrounded: int = 0
    dropped_nonmember: int = 0


def composition_window(text: str, tail: int = 800, fallback: int = 4000) -> str:
    """Slice the roster region from full report text.

    Anchors on the *last* composition heading — the first occurrence is
    usually the table of contents. Ends shortly after the SECRETARIAT
    block, or ``fallback`` chars in reports without one.
    """
    start = text.rfind(COMPOSITION_HEADING)
    if start == -1:
        raise ValueError("no composition heading in text")
    end_match = re.search(r"SECRETARIAT", text[start:])
    end = start + end_match.end() + tail if end_match else start + fallback
    return text[start:end]


def assign_sections(
    members: list[RosterMember], window: str, default_section: str | None = None
) -> None:
    """Set each member's section from the nearest preceding section header.

    Members before any header (single-chamber committees print no house
    headers inside the roster) get ``default_section``.
    """
    headers = sorted(
        (m.start(), h)
        for h in SECTION_HEADERS
        for m in re.finditer(re.escape(h), window)
    )
    for member in members:
        section = default_section
        for pos, name in headers:
            if pos < member.start:
                section = name
            else:
                break
        member.section = section


def _langextract_fn(model_id: str, model_url: str, timeout: int) -> Callable[[str], list[Any]]:
    import langextract as lx

    example = lx.data.ExampleData(
        text=_EXAMPLE_TEXT,
        extractions=[
            lx.data.Extraction(extraction_class=cls, extraction_text=txt)
            for cls, txt in _EXAMPLE_ENTITIES
        ],
    )

    def run(window: str) -> list[Any]:
        result = lx.extract(
            text_or_documents=window,
            prompt_description=_PROMPT,
            examples=[example],
            model_id=model_id,
            model_url=model_url,
            fence_output=False,
            use_schema_constraints=False,
            language_model_params={"timeout": timeout},
        )
        return list(result.extractions)

    return run


class RosterExtractor:
    """Extract a grounded roster from committee-report text.

    ``extract_fn`` takes the window text and returns langextract-shaped
    extraction objects (``extraction_class``, ``extraction_text``,
    ``char_interval``); inject a fake in tests to avoid the LLM.
    """

    def __init__(
        self,
        model_id: str = "qwen2.5:3b",
        model_url: str = "http://localhost:11434",
        timeout: int = 600,
        extract_fn: Callable[[str], list[Any]] | None = None,
    ):
        self._extract_fn = extract_fn or _langextract_fn(model_id, model_url, timeout)

    def extract(self, text: str, default_section: str | None = None) -> RosterResult:
        window = composition_window(text)
        result = RosterResult()
        for ext in self._extract_fn(window):
            if ext.char_interval is None:
                result.dropped_ungrounded += 1
                continue
            if ext.extraction_class == "vacancy":
                result.vacancies += 1
            elif ext.extraction_class == "member":
                if not _HONORIFIC_RE.match(ext.extraction_text.strip()):
                    result.dropped_nonmember += 1
                    continue
                result.members.append(
                    RosterMember(
                        name=ext.extraction_text,
                        start=ext.char_interval.start_pos,
                        end=ext.char_interval.end_pos,
                        section=None,
                    )
                )
        assign_sections(result.members, window, default_section)
        return result
