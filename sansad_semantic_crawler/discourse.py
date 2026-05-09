"""Phase 2: surface discourse classifier — the prose of counterinsurgency.

Classifies a ministry response by its **actual political function**, not
its surface politeness. Reads ``answers.jsonl`` (Phase 1 output) and
writes ``analysis_discourse.jsonl`` (Phase 4 input).

Eight discourse labels, **locked** for v0.5.0 (per
``notes/PLAN_v0.5.0_SCOPE.md``):

* ``ACCEPTED`` — concrete commitment with specifics (rare).
* ``DEFLECTED`` — indefinite deferral via present-continuous.
* ``ABSORBED`` — "noted" / "appreciated" — clock-running.
* ``REJECTED`` — flat refusal, often citing constraints.
* ``SUBSTITUTED`` — replaces the question's metric with the ministry's.
* ``DATA_WITHHELD`` — "no separate data is maintained" (Q/A-specific).
* ``SCOPE_NARROWED`` — "so far as this Ministry is concerned"
  (Q/A-specific jurisdiction dodge).
* ``CIRCULAR_REFERENCE`` — points back to its own earlier non-answer
  (committee-specific).

Adding a new label is **safe** (additive). Renaming or removing one is
a **breaking change** for downstream consumers (weighting engine,
front-end consumers). Add only at major-version boundaries with an
``upgrade_notes`` line in the GitHub Release.

This module is **deterministic and traceable**, not authoritative
(Power, *Making Things Auditable*). ``UNCLASSIFIED`` records are not
failures; they are flags for human review or a future LLM tier.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

CLASSIFIER_VERSION = "regex_v1"

# Channel labels travel with each classification so cross-channel queries
# ("how does the same ministry's evasion grammar differ between Q/A and
# committee responses?") work without reconstruction.
CHANNEL_QA = "qa"
CHANNEL_COMMITTEE = "committee"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Pattern library — drawn from ATR + Q/A language across actual reports.
# Each entry: list of compiled regex patterns + a one-line political function.
# ---------------------------------------------------------------------------


@dataclass
class _LabelDef:
    name: str
    political_function: str
    patterns: tuple[re.Pattern, ...]
    channel_scope: str  # 'shared' | 'qa' | 'committee'


def _compile(patterns: Iterable[str]) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


# Shared evasion grammar. The same phrases appear in Q/A answers and ATR
# responses because the bureaucratic register is channel-agnostic.

_ACCEPTED = _LabelDef(
    "ACCEPTED",
    "Concrete commitment with specifics. Verify implementation timeline.",
    _compile([
        r"(?:ministry|department|government)\s+(?:has\s+(?:decided|agreed|approved))",
        r"(?:orders?|notification|circular)\s+(?:has\s+been|have\s+been)\s+(?:issued|notified)",
        r"(?:with\s+effect\s+from|w\.?e\.?f\.?)\s+\d",
        r"(?:sanctioned|approved|allocated)\s+(?:an?\s+)?(?:amount|sum|budget)\s+of\s+Rs\.?",
    ]),
    "shared",
)

_REJECTED = _LabelDef(
    "REJECTED",
    "Flat refusal. The committee's recommendation is dead on arrival.",
    _compile([
        r"(?:ministry|department|government)\s+(?:does\s+not|do\s+not)\s+(?:agree|concur)",
        r"(?:not\s+)?(?:feasible|practicable|possible)\s+(?:at\s+(?:this|the\s+present))",
        r"(?:may\s+not\s+be|is\s+not)\s+(?:feasible|desirable|appropriate|necessary)",
        r"no\s+such\s+(?:proposal|plan|scheme)\s+(?:is\s+under|exists)",
        r"does\s+not\s+arise",
        r"constraints?\s+(?:of\s+)?(?:resources?|funds?|budget|manpower)",
    ]),
    "shared",
)

_SUBSTITUTED = _LabelDef(
    "SUBSTITUTED",
    "Replaced the question's framing with the ministry's preferred metric. "
    "The original question is unanswered.",
    _compile([
        r"mission\s+mode",
        r"flagship\s+(?:programme|scheme|initiative)",
        r"total\s+(?:number\s+of\s+)?(?:appointments|recruitments)\s+(?:made|done|completed)",
        r"\d[\d,]+\s+(?:posts?|positions?|vacancies)\s+(?:have\s+been|were)\s+(?:filled|recruited|appointed)",
        r"(?:under|through)\s+the\s+(?:scheme|initiative|programme)\s+of",
    ]),
    "shared",
)

_DEFLECTED = _LabelDef(
    "DEFLECTED",
    "Indefinite deferral. No timeline, no commitment, no accountability trigger.",
    _compile([
        # Allow 0-2 intermediate adjectives ("under active consideration",
        # "under careful and ongoing review") — real ministry register often
        # qualifies rather than committing.
        r"(?:matter|issue|recommendation)\s+is\s+(?:under|being)(?:\s+\w+){0,2}\s+(?:consideration|examined|reviewed|looked\s+into)",
        r"(?:steps|measures|action)\s+(?:are|is)\s+being\s+taken",
        r"(?:will\s+be|shall\s+be)\s+(?:considered|examined|taken\s+up|looked\s+into)",
        r"in\s+due\s+course",
        r"at\s+an?\s+appropriate\s+(?:time|stage|juncture)",
        r"data\s+is\s+being\s+(?:compiled|collected|tabulated)",
    ]),
    "shared",
)

_ABSORBED = _LabelDef(
    "ABSORBED",
    "Acknowledged without commitment. Designed to exhaust the parliamentary clock.",
    _compile([
        r"(?:recommendation|observation)\s+(?:has\s+been|is)\s+noted",
        r"noted\s+for\s+(?:future\s+)?(?:compliance|guidance|reference)",
        r"(?:ministry|department)\s+(?:agrees\s+with|appreciates)\s+the\s+(?:concern|sentiment|spirit)",
        r"in\s+(?:the\s+)?spirit\s+of\s+the\s+recommendation",
    ]),
    "shared",
)

# Q/A-specific: written-answer evasions that committees don't typically use.
_DATA_WITHHELD = _LabelDef(
    "DATA_WITHHELD",
    "Data exists but is withheld or deliberately not collected. "
    "The absence of data is itself a political choice.",
    _compile([
        r"(?:no\s+such|no\s+separate|no\s+specific)\s+(?:data|information|record)\s+(?:is\s+)?(?:maintained|available|kept)",
        r"(?:information|data)\s+(?:is\s+)?(?:not\s+(?:maintained|available|compiled))",
        r"(?:centrally\s+)?(?:not\s+maintained|not\s+collected)",
        r"(?:information|data)\s+(?:is\s+being|will\s+be)\s+(?:collected|compiled|laid\s+on\s+the\s+Table)",
    ]),
    "qa",
)

_SCOPE_NARROWED = _LabelDef(
    "SCOPE_NARROWED",
    "Jurisdiction dodge. Narrows the scope to avoid answering the actual question.",
    _compile([
        r"(?:so\s+far\s+as|in\s+so\s+far\s+as)\s+(?:this|the)\s+(?:ministry|department)\s+is\s+concerned",
        r"does\s+not\s+(?:fall|come)\s+(?:within|under)\s+the\s+(?:purview|jurisdiction)",
        r"(?:matter|subject)\s+(?:pertains|relates)\s+to\s+(?:state|respective)\s+(?:governments?|authorities)",
    ]),
    "qa",
)

# Committee-specific: ATR closures via reference to prior responses.
_CIRCULAR_REFERENCE = _LabelDef(
    "CIRCULAR_REFERENCE",
    "Points back to its own earlier non-answer. The accountability loop closes.",
    _compile([
        r"in\s+(?:continuation|pursuance)\s+of\s+the\s+(?:earlier|previous)\s+(?:reply|response)",
        r"(?:ministry|department)\s+reiterates\s+(?:its|their)\s+(?:earlier|previous)",
        r"as\s+stated\s+in\s+(?:the\s+)?(?:reply|response)\s+to\s+(?:Recommendation|Rec\.?)\s+No\.?",
        r"as\s+(?:already|earlier)\s+(?:stated|mentioned|informed|intimated)",
    ]),
    "committee",
)

# Order matters: priority is highest-specificity first. Channel-specific
# labels precede shared labels so a Q/A response containing both a
# DATA_WITHHELD pattern and a generic DEFLECTED pattern gets the more
# specific label.
_PRIORITY_QA = (_DATA_WITHHELD, _SCOPE_NARROWED, _ACCEPTED, _REJECTED, _SUBSTITUTED, _DEFLECTED, _ABSORBED)
_PRIORITY_COMMITTEE = (_CIRCULAR_REFERENCE, _ACCEPTED, _REJECTED, _SUBSTITUTED, _DEFLECTED, _ABSORBED)

# Confidence per label: chosen empirically, can be tuned. Higher means we
# trust the regex match more strongly (less chance of false positive).
_CONFIDENCE: dict[str, float] = {
    "ACCEPTED": 0.85,        # very specific patterns (Rs. amounts, w.e.f. dates)
    "REJECTED": 0.90,        # near-impossible to misread "does not agree"
    "SUBSTITUTED": 0.75,     # "Mission Mode" can appear as topic, not framing
    "DEFLECTED": 0.85,
    "ABSORBED": 0.80,
    "DATA_WITHHELD": 0.85,
    "SCOPE_NARROWED": 0.85,
    "CIRCULAR_REFERENCE": 0.85,
}


@dataclass
class DiscourseClassification:
    label: str  # one of the eight, or "UNCLASSIFIED"
    confidence: float
    matched_pattern: str
    political_function: str
    channel: str  # 'qa' | 'committee'
    classifier: str = CLASSIFIER_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


def _empty_classification(channel: str) -> DiscourseClassification:
    return DiscourseClassification(
        label="UNCLASSIFIED",
        confidence=0.0,
        matched_pattern="",
        political_function="No pattern matched. Candidate for LLM-tier review.",
        channel=channel,
    )


def classify_response(text: str, channel: str) -> DiscourseClassification:
    """Classify a single ministry response by its political function.

    ``channel`` is ``'qa'`` (Q/A answer) or ``'committee'`` (ATR response).
    Patterns are matched in channel-aware priority order; the first hit wins.

    Returns ``UNCLASSIFIED`` when no pattern matches; this is information,
    not failure. Downstream consumers can filter or escalate.
    """
    if not text or not text.strip():
        return _empty_classification(channel)
    priority = _PRIORITY_QA if channel == CHANNEL_QA else _PRIORITY_COMMITTEE
    for label_def in priority:
        for pattern in label_def.patterns:
            m = pattern.search(text)
            if m:
                return DiscourseClassification(
                    label=label_def.name,
                    confidence=_CONFIDENCE[label_def.name],
                    matched_pattern=m.group(0)[:120],
                    political_function=label_def.political_function,
                    channel=channel,
                )
    return _empty_classification(channel)


# ---------------------------------------------------------------------------
# Corpus dispatcher
# ---------------------------------------------------------------------------


@dataclass
class AnalysisStats:
    qa_classified: int = 0
    atr_classified: int = 0
    dfg_passed_through: int = 0
    skipped_empty_response: int = 0
    sources_processed: int = 0
    label_counts: dict[str, int] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def analyse_discourse(out_dir: Path, *, refresh: bool = False, log_fn=print) -> AnalysisStats:
    """Walk ``answers.jsonl``, classify each response, write
    ``analysis_discourse.jsonl``.

    Dispatch:

    * ``kind == 'qa_response'``: classify ``answer_text`` with ``channel='qa'``.
    * ``kind == 'atr_response'``: classify ``response_text`` with
      ``channel='committee'``.
    * ``kind == 'dfg_recommendation'``: passed through with
      ``discourse_label = null`` — these are committee asks awaiting a
      future ATR; nothing to classify yet. Cross-link to a future ATR
      response by ``(committee_slug, recommendation_no)`` is Phase 4 work.

    Output records are joinable to ``answers.jsonl`` and ``manifest.jsonl``
    via ``key``; multiple analysis rows per ``key`` are possible
    (one per recommendation in an ATR).
    """
    stats = AnalysisStats()
    answers_path = out_dir / "answers.jsonl"
    out_path = out_dir / "analysis_discourse.jsonl"
    if not answers_path.exists():
        log_fn(f"no answers.jsonl at {answers_path} — run extract-answers first")
        return stats

    rows = _read_jsonl(answers_path)
    out_records: list[dict] = []
    for row in rows:
        stats.sources_processed += 1
        kind = row.get("kind")
        # Carry common provenance fields forward so consumers can join
        # without re-reading answers.jsonl.
        common = {
            "key": row.get("key"),
            "run_id": row.get("run_id"),
            "answers_extractor": row.get("extractor"),
            "answers_extracted_at": row.get("extracted_at"),
            "source_pdf": row.get("source_pdf"),
            "language_classified": row.get("language_classified") or ["en"],
            "classified_at": _now(),
            "classifier": CLASSIFIER_VERSION,
        }
        try:
            if kind == "qa_response":
                text = row.get("answer_text") or ""
                if not text.strip():
                    stats.skipped_empty_response += 1
                    continue
                cls = classify_response(text, CHANNEL_QA)
                rec = {
                    **common,
                    "kind": "qa_response_analysis",
                    **cls.to_dict(),
                    "text_excerpt": text[:200],
                }
                out_records.append(rec)
                stats.qa_classified += 1
                stats.label_counts[cls.label] = stats.label_counts.get(cls.label, 0) + 1

            elif kind == "atr_response":
                text = row.get("response_text") or ""
                if not text.strip():
                    stats.skipped_empty_response += 1
                    continue
                cls = classify_response(text, CHANNEL_COMMITTEE)
                rec = {
                    **common,
                    "kind": "atr_response_analysis",
                    "recommendation_no": row.get("recommendation_no"),
                    **cls.to_dict(),
                    "text_excerpt": text[:200],
                }
                out_records.append(rec)
                stats.atr_classified += 1
                stats.label_counts[cls.label] = stats.label_counts.get(cls.label, 0) + 1

            elif kind == "dfg_recommendation":
                # Committee ask without a response yet. Pass through with
                # discourse_label=None so consumers can join cleanly.
                rec = {
                    **common,
                    "kind": "dfg_recommendation_passthrough",
                    "recommendation_no": row.get("recommendation_no"),
                    "label": None,
                    "confidence": None,
                    "matched_pattern": None,
                    "political_function": None,
                    "channel": "dfg",
                }
                out_records.append(rec)
                stats.dfg_passed_through += 1

        except Exception as exc:  # noqa: BLE001
            stats.errors.append({"key": row.get("key"), "error": repr(exc)})

    # Atomic write.
    tmp = out_path.with_name(out_path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for rec in out_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(out_path)

    label_summary = ", ".join(f"{k}={v}" for k, v in sorted(stats.label_counts.items()))
    log_fn(
        f"analysis_discourse.jsonl: qa={stats.qa_classified} "
        f"atr={stats.atr_classified} dfg_passthrough={stats.dfg_passed_through} "
        f"skipped_empty={stats.skipped_empty_response} errors={len(stats.errors)}"
    )
    if label_summary:
        log_fn(f"  labels: {label_summary}")
    return stats
