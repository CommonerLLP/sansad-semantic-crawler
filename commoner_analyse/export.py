from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .aggregations import _classify_label, _EVASIVE, _SUBSTANTIVE
from .discourse import DISCOURSE_LABEL_DESCRIPTIONS
from .textparse import read_jsonl
from .topics import TopicProfile


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_glossary() -> dict[str, Any]:
    """The discourse label taxonomy as data, for consumers across a licensing
    boundary that can't import this package directly (e.g. ``zero-hour``,
    which reads generated JSONL/JS but never imports ``commoner_analyse``).

    Exporting this as data — rather than each consumer hand-copying
    ``DISCOURSE_LABEL_DESCRIPTIONS`` into their own source — is how a
    consumer's copy stays in sync with the taxonomy as labels are added,
    renamed, or retired here.
    """
    return {
        "generatedAt": now(),
        "labels": [
            {"label": label, "description": description, "function": _classify_label(label)}
            for label, description in DISCOURSE_LABEL_DESCRIPTIONS.items()
        ],
    }


def question_label(rec: dict[str, Any]) -> str:
    qtype = (rec.get("qtype") or "").strip()
    qno = rec.get("qno") or "?"
    return f"{rec.get('house')} {qtype + ' ' if qtype else ''}Q.{qno}"


def source_href(rec: dict[str, Any]) -> str | None:
    return rec.get("uri") or rec.get("pdf_url") or rec.get("pdf_path")


def build_discourse_summary(out_dir: Path) -> dict[str, Any] | None:
    """Corpus-wide discourse summary, merging manifest.jsonl + analysis_discourse.jsonl.

    Returns ``None`` if ``analysis_discourse.jsonl`` doesn't exist (i.e.
    ``analyse-discourse`` hasn't been run for this corpus) so callers can
    omit the field entirely rather than emit a hollow all-zero summary.
    Uses the same substantive/evasive split as ``aggregations.py`` so this
    number always agrees with ``write_ministry_summary``'s per-ministry rows.
    """
    discourse_path = out_dir / "analysis_discourse.jsonl"
    if not discourse_path.exists():
        return None
    manifest_total = len(read_jsonl(out_dir / "manifest.jsonl"))
    discourse = read_jsonl(discourse_path)
    labels = Counter(row.get("label") or "UNCLASSIFIED" for row in discourse)
    evasive = sum(c for lab, c in labels.items() if lab in _EVASIVE)
    substantive = sum(c for lab, c in labels.items() if lab in _SUBSTANTIVE)
    classified = evasive + substantive
    return {
        "questionsTotal": manifest_total,
        "responsesExtracted": len(discourse),
        "responsesClassified": classified,
        "evasiveCount": evasive,
        "substantiveCount": substantive,
        "evasionRateClassified": round(evasive / classified, 4) if classified else None,
        "labelDistribution": dict(labels.most_common()),
    }


def build_ministry_discourse(out_dir: Path) -> list[dict[str, Any]] | None:
    """Per-ministry discourse rollup from ``ministry_summary_qa.jsonl``.

    Returns ``None`` if that file doesn't exist (``analyse-ministry`` hasn't
    been run), matching ``build_discourse_summary``'s "omit, don't zero" rule.
    """
    rows = read_jsonl(out_dir / "ministry_summary_qa.jsonl")
    if not rows:
        return None
    return [
        {
            "ministry": row["ministry"],
            "recordsTotal": row.get("records_total", 0),
            "recordsClassified": row.get("records_classified", 0),
            "recordsUnclassified": row.get("records_unclassified", 0),
            "evasionRateClassified": row.get("evasion_rate_classified"),
            "labelDistribution": row.get("label_distribution", {}),
            "perEvasionShare": row.get("per_evasion_label_share", {}),
        }
        for row in sorted(rows, key=lambda r: -r.get("records_total", 0))
    ]


def build_summary(topic: TopicProfile, out_dir: Path, *, max_questions: int = 25) -> dict[str, Any]:
    rows = read_jsonl(out_dir / "analysis.jsonl")
    by_house = Counter(row.get("house") or "Unknown" for row in rows)
    by_tag = Counter(tag for row in rows for tag in row.get("tags", []))
    years = sorted({int(row["date"][:4]) for row in rows if str(row.get("date", ""))[:4].isdigit()})
    ranked = sorted(rows, key=lambda r: (-float(r.get("score") or 0), r.get("date") or ""))
    labels = topic.tag_labels
    discourse_summary = build_discourse_summary(out_dir)
    ministry_discourse = build_ministry_discourse(out_dir)
    summary: dict[str, Any] = {
        "topic": topic.name,
        "description": topic.description,
        "generatedAt": now(),
        "sourceManifest": str(out_dir / "manifest.jsonl"),
        "summaryStats": [
            {"label": "Questions in corpus", "value": str(len(rows)), "sub": "Normalized Lok Sabha + Rajya Sabha records."},
            {"label": "Lok Sabha", "value": str(by_house.get("Lok Sabha", 0)), "sub": "From elibrary.sansad.in."},
            {"label": "Rajya Sabha", "value": str(by_house.get("Rajya Sabha", 0)), "sub": "From rsdoc.nic.in."},
            {"label": "Years covered", "value": f"{years[0]}-{years[-1]}" if years else "None", "sub": "Based on local manifest records."},
        ],
        "topTags": [
            {"tag": tag, "label": labels.get(tag, tag), "count": count}
            for tag, count in by_tag.most_common(20)
        ],
        "keyQuestions": [
            {
                "label": question_label(row),
                "title": row.get("title") or "Untitled question",
                "date": row.get("date"),
                "ministry": row.get("ministry"),
                "askers": row.get("askers") or [],
                "tags": row.get("tags") or [],
                "score": row.get("score"),
                "excerpt": row.get("excerpt"),
                "source": row.get("source"),
                "href": source_href(row),
            }
            for row in ranked[:max_questions]
        ],
    }
    if discourse_summary is not None:
        summary["discourseSummary"] = discourse_summary
    if ministry_discourse is not None:
        summary["ministryDiscourse"] = ministry_discourse
    return summary


def write_export(data: dict[str, Any], path: Path, *, fmt: str, js_global: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent=2)
    if fmt == "js":
        path.write_text(f"window.{js_global} = {body};\n", encoding="utf-8")
    else:
        path.write_text(body + "\n", encoding="utf-8")

