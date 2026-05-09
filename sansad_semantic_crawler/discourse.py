"""Phase 2: surface discourse classifier — the prose of counterinsurgency.

Classifies a ministry response by its **actual political function**, not
its surface politeness. Reads ``answers.jsonl`` (Phase 1 output) and
writes ``analysis_discourse.jsonl`` (Phase 4 input).

Nine discourse labels (eight regex-matched + one LLM-tier addition):

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
* ``FACTUAL_DISCLOSURE`` — direct factual recitation without evasion or
  new commitment (LLM-tier only; regex does not fire this label).

Adding a new label is **safe** (additive). Renaming or removing one is
a **breaking change** for downstream consumers (weighting engine,
front-end consumers). Add only at major-version boundaries.

Two classifier tiers:

1. **Regex tier** (``CLASSIFIER_VERSION = 'regex_v1'``): deterministic,
   zero latency, no external deps. Fires first on every record.

2. **LLM tier** (``LLM_CLASSIFIER_VERSION = 'llm_discourse_v1'``):
   calls an Ollama-compatible endpoint for records the regex tier leaves
   UNCLASSIFIED. Enabled explicitly with ``llm_tier=True`` in
   ``analyse_discourse`` (or ``--llm-tier`` on the CLI). Requires a
   running Ollama instance (default ``http://localhost:11434/v1``).

This module is **deterministic and traceable**, not authoritative.
``UNCLASSIFIED`` records are not failures; they are flags for human
review or LLM-tier escalation.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib import request as _url_request
from urllib.error import HTTPError, URLError

CLASSIFIER_VERSION = "regex_v1"
LLM_CLASSIFIER_VERSION = "llm_discourse_v1"

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

# Confidence per label: chosen empirically. Higher means we trust the regex
# match more strongly (less chance of false positive).
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


# ---------------------------------------------------------------------------
# LLM tier — taxonomy descriptions + prompt construction
# ---------------------------------------------------------------------------

# All nine labels with plain-English descriptions used in the LLM system
# prompt. Keeping these in a public dict lets callers (tests, notebooks)
# inspect what the model is asked to decide between.
DISCOURSE_LABEL_DESCRIPTIONS: dict[str, str] = {
    "ACCEPTED": (
        "Concrete commitment with specifics: a budget allocation, notification issued, "
        "an order with w.e.f. date, or an approved scheme with named timeline."
    ),
    "DEFLECTED": (
        "Indefinite deferral with no timeline or accountability trigger: "
        "'under consideration', 'steps are being taken', 'will be examined', "
        "'in due course'."
    ),
    "ABSORBED": (
        "Acknowledged without commitment: 'noted', 'ministry appreciates the concern', "
        "'in the spirit of the recommendation'. The clock runs out."
    ),
    "REJECTED": (
        "Flat refusal: 'does not agree', 'not feasible', 'does not arise', "
        "'resource constraints'. The recommendation or question is dead."
    ),
    "SUBSTITUTED": (
        "Replaces the question's metric with the ministry's preferred framing: "
        "cites total recruitments instead of vacancies, flagship scheme totals "
        "instead of the specific issue raised."
    ),
    "DATA_WITHHELD": (
        "Data exists but is not provided: 'no separate data maintained', "
        "'information not centrally compiled', 'data is being collected'. "
        "The withholding is a deliberate choice. (QA channel only.)"
    ),
    "SCOPE_NARROWED": (
        "Narrows scope to dodge the question: 'so far as this Ministry is concerned', "
        "'does not fall within the purview', 'pertains to State Governments'. "
        "(QA channel only.)"
    ),
    "CIRCULAR_REFERENCE": (
        "Points to its own earlier non-answer: 'in continuation of earlier reply', "
        "'ministry reiterates its earlier position', 'as already stated in reply to "
        "Recommendation No. X'. (Committee channel only.)"
    ),
    "FACTUAL_DISCLOSURE": (
        "Direct factual recitation without evasion, new commitment, or withholding: "
        "lists programme details, district counts, budget outlays, beneficiary figures, "
        "scheme progress. The ministry answers the question with data."
    ),
}


def _build_llm_system_prompt() -> str:
    """Construct the LLM system prompt from the shared taxonomy dictionary."""
    taxonomy_lines = "\n".join(
        f"- {label}: {desc}"
        for label, desc in DISCOURSE_LABEL_DESCRIPTIONS.items()
    )
    return (
        "You are classifying the political function of an Indian parliamentary "
        "ministry response. Choose ONE label that best describes the response.\n\n"
        "Labels:\n"
        + taxonomy_lines
        + "\n\nRules:\n"
        "- Return EXACTLY ONE label from the list above.\n"
        "- When multiple labels apply, prefer the most specific: DATA_WITHHELD > "
        "DEFLECTED; CIRCULAR_REFERENCE > ABSORBED; FACTUAL_DISCLOSURE only when "
        "no evasion whatsoever is present.\n"
        "- Channel hint: 'qa' = written parliamentary Q&A answer; "
        "'committee' = Action-Taken Report response.\n"
        "- DATA_WITHHELD and SCOPE_NARROWED apply to 'qa' channel only.\n"
        "- CIRCULAR_REFERENCE applies to 'committee' channel only.\n\n"
        'Return JSON only: {"label": "ONE_LABEL", "confidence": 0.0, "reasoning": "one sentence"}'
    )


# Pre-build once at import time (cheap; the dict is a constant).
_LLM_SYSTEM_PROMPT: str = _build_llm_system_prompt()

# Max chars of response text sent to the LLM. Beyond this, the response is
# truncated — LLMs perform better on focused excerpts and context windows are
# finite. Full text is still stored in answers.jsonl.
_LLM_TEXT_LIMIT = 2000


@dataclass
class DiscourseClassification:
    label: str  # one of the nine, or "UNCLASSIFIED"
    confidence: float
    matched_pattern: str  # regex group or LLM reasoning excerpt
    political_function: str
    channel: str  # 'qa' | 'committee'
    classifier: str = CLASSIFIER_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


def _empty_classification(channel: str, reason: str = "") -> DiscourseClassification:
    return DiscourseClassification(
        label="UNCLASSIFIED",
        confidence=0.0,
        matched_pattern="",
        political_function=reason or "No pattern matched. Candidate for LLM-tier review.",
        channel=channel,
    )


# ---------------------------------------------------------------------------
# Regex classifier (Tier 1)
# ---------------------------------------------------------------------------


def classify_response(text: str, channel: str) -> DiscourseClassification:
    """Classify a single ministry response by its political function (regex tier).

    ``channel`` is ``'qa'`` (Q/A answer) or ``'committee'`` (ATR response).
    Patterns are matched in channel-aware priority order; the first hit wins.

    Returns ``UNCLASSIFIED`` when no pattern matches; this is information,
    not failure. Pass the result to ``classify_response_llm`` to attempt a
    second-tier classification.
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
# LLM classifier (Tier 2) — Ollama-compatible chat completions
# ---------------------------------------------------------------------------


def _discourse_http_post(
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout_s: float,
) -> str:
    """POST to an Ollama-compatible chat completions endpoint; return raw content."""
    base = endpoint.rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    req = _url_request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer local",
        },
        method="POST",
    )
    try:
        with _url_request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"].get("content") or "{}"
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"LLM endpoint unreachable: {exc}") from exc


def _parse_llm_json(content: str) -> dict[str, Any]:
    """Parse JSON from LLM output; falls back to extracting the first {...} block."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def classify_response_llm(
    text: str,
    channel: str,
    *,
    endpoint: str = "http://localhost:11434/v1",
    model: str = "qwen2.5:7b",
    timeout_s: float = 30.0,
    _http_post: Callable[[str, dict[str, Any], float], str] | None = None,
) -> DiscourseClassification:
    """LLM second-pass classifier for records the regex tier left UNCLASSIFIED.

    Calls an Ollama-compatible ``/v1/chat/completions`` endpoint.  Falls back
    to UNCLASSIFIED (with an error note in ``political_function``) on any
    network or parse failure so the corpus dispatcher never raises.

    Parameters
    ----------
    text:
        The ministry response text.
    channel:
        ``'qa'`` or ``'committee'`` — passed to the model as a channel hint.
    endpoint:
        Base URL of the Ollama (or OpenAI-compatible) server.
    model:
        Model name recognised by the endpoint (e.g. ``'qwen2.5:7b'``).
    timeout_s:
        HTTP request timeout in seconds.
    _http_post:
        Injection point for tests. When provided, called as
        ``_http_post(endpoint, payload, timeout_s)`` instead of the real
        HTTP layer.
    """
    if not text or not text.strip():
        return _empty_classification(channel)

    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _LLM_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Channel: {channel}\n\nText:\n{text[:_LLM_TEXT_LIMIT]}"
                ),
            },
        ],
    }

    try:
        http_fn = _http_post or _discourse_http_post
        raw_content = http_fn(endpoint, payload, timeout_s=timeout_s)
        parsed = _parse_llm_json(raw_content)
        label = str(parsed.get("label") or "").strip().upper()
        if label not in DISCOURSE_LABEL_DESCRIPTIONS:
            return _empty_classification(
                channel,
                reason=f"LLM returned unrecognised label: {label!r}",
            )
        reasoning = str(parsed.get("reasoning") or "")[:120]
        confidence = float(parsed.get("confidence") or 0.75)
        confidence = min(1.0, max(0.0, confidence))
        return DiscourseClassification(
            label=label,
            confidence=confidence,
            matched_pattern=reasoning,
            political_function=DISCOURSE_LABEL_DESCRIPTIONS[label],
            channel=channel,
            classifier=LLM_CLASSIFIER_VERSION,
        )
    except Exception as exc:  # noqa: BLE001
        return _empty_classification(
            channel,
            reason=f"LLM tier failed: {str(exc)[:80]}",
        )


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
    llm_classified: int = 0    # records upgraded from UNCLASSIFIED by LLM tier
    llm_unresolved: int = 0    # LLM called but response still UNCLASSIFIED
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


def analyse_discourse(
    out_dir: Path,
    *,
    refresh: bool = False,
    log_fn: Callable[..., None] = print,
    llm_tier: bool = False,
    llm_endpoint: str = "http://localhost:11434/v1",
    llm_model: str = "qwen2.5:7b",
    llm_timeout_s: float = 30.0,
    _llm_http_post: Callable[[str, dict[str, Any], float], str] | None = None,
) -> AnalysisStats:
    """Walk ``answers.jsonl``, classify each response, write
    ``analysis_discourse.jsonl``.

    Dispatch:

    * ``kind == 'qa_response'``: classify ``answer_text`` with ``channel='qa'``.
    * ``kind == 'atr_response'``: classify ``response_text`` with
      ``channel='committee'``.
    * ``kind == 'dfg_recommendation'``: passed through with
      ``discourse_label = null`` — these are committee asks awaiting a
      future ATR; nothing to classify yet.

    When ``llm_tier=True``, any record the regex tier leaves as UNCLASSIFIED
    is sent to the LLM endpoint for a second-pass classification. The LLM
    result replaces the UNCLASSIFIED placeholder in the output record. The
    ``classifier`` field distinguishes ``'regex_v1'`` from ``'llm_discourse_v1'``
    results.

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
                cls = _maybe_llm_upgrade(
                    cls, text, CHANNEL_QA, stats,
                    enabled=llm_tier,
                    endpoint=llm_endpoint,
                    model=llm_model,
                    timeout_s=llm_timeout_s,
                    _http_post=_llm_http_post,
                )
                rec = {
                    **common,
                    "kind": "qa_response_analysis",
                    **cls.to_dict(),
                    "text_excerpt": text[:200],
                }
                # Override classifier field so LLM-upgraded records are traceable.
                rec["classifier"] = cls.classifier
                out_records.append(rec)
                stats.qa_classified += 1
                stats.label_counts[cls.label] = stats.label_counts.get(cls.label, 0) + 1

            elif kind == "atr_response":
                text = row.get("response_text") or ""
                if not text.strip():
                    stats.skipped_empty_response += 1
                    continue
                cls = classify_response(text, CHANNEL_COMMITTEE)
                cls = _maybe_llm_upgrade(
                    cls, text, CHANNEL_COMMITTEE, stats,
                    enabled=llm_tier,
                    endpoint=llm_endpoint,
                    model=llm_model,
                    timeout_s=llm_timeout_s,
                    _http_post=_llm_http_post,
                )
                rec = {
                    **common,
                    "kind": "atr_response_analysis",
                    "recommendation_no": row.get("recommendation_no"),
                    **cls.to_dict(),
                    "text_excerpt": text[:200],
                }
                rec["classifier"] = cls.classifier
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
    llm_note = (
        f" llm_upgraded={stats.llm_classified} llm_unresolved={stats.llm_unresolved}"
        if llm_tier else ""
    )
    log_fn(
        f"analysis_discourse.jsonl: qa={stats.qa_classified} "
        f"atr={stats.atr_classified} dfg_passthrough={stats.dfg_passed_through} "
        f"skipped_empty={stats.skipped_empty_response} errors={len(stats.errors)}"
        + llm_note
    )
    if label_summary:
        log_fn(f"  labels: {label_summary}")
    return stats


def _maybe_llm_upgrade(
    cls: DiscourseClassification,
    text: str,
    channel: str,
    stats: AnalysisStats,
    *,
    enabled: bool,
    endpoint: str,
    model: str,
    timeout_s: float,
    _http_post: Callable[[str, dict[str, Any], float], str] | None,
) -> DiscourseClassification:
    """If ``cls`` is UNCLASSIFIED and ``enabled``, call the LLM tier.

    Updates ``stats.llm_classified`` or ``stats.llm_unresolved`` in-place.
    Never raises.
    """
    if not enabled or cls.label != "UNCLASSIFIED":
        return cls
    llm_cls = classify_response_llm(
        text, channel,
        endpoint=endpoint,
        model=model,
        timeout_s=timeout_s,
        _http_post=_http_post,
    )
    if llm_cls.label != "UNCLASSIFIED":
        stats.llm_classified += 1
        return llm_cls
    stats.llm_unresolved += 1
    return cls
