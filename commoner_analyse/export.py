from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .textparse import read_jsonl
from .topics import TopicProfile


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def question_label(rec: dict[str, Any]) -> str:
    qtype = (rec.get("qtype") or "").strip()
    qno = rec.get("qno") or "?"
    return f"{rec.get('house')} {qtype + ' ' if qtype else ''}Q.{qno}"


def source_href(rec: dict[str, Any]) -> str | None:
    return rec.get("uri") or rec.get("pdf_url") or rec.get("pdf_path")


def build_summary(topic: TopicProfile, out_dir: Path, *, max_questions: int = 25) -> dict[str, Any]:
    rows = read_jsonl(out_dir / "analysis.jsonl")
    by_house = Counter(row.get("house") or "Unknown" for row in rows)
    by_tag = Counter(tag for row in rows for tag in row.get("tags", []))
    years = sorted({int(row["date"][:4]) for row in rows if str(row.get("date", ""))[:4].isdigit()})
    ranked = sorted(rows, key=lambda r: (-float(r.get("score") or 0), r.get("date") or ""))
    labels = topic.tag_labels
    return {
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


def write_export(data: dict[str, Any], path: Path, *, fmt: str, js_global: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent=2)
    if fmt == "js":
        path.write_text(f"window.{js_global} = {body};\n", encoding="utf-8")
    else:
        path.write_text(body + "\n", encoding="utf-8")

