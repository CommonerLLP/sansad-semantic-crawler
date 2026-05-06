from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .topics import TopicProfile


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def clean_htmlish(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", text).strip()


def extract_pdf_text(path: Path) -> str:
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        from pdfminer.high_level import extract_text  # type: ignore

        return extract_text(str(path))
    except Exception:  # noqa: BLE001
        return ""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def text_path_for(out_dir: Path, rec: dict[str, Any]) -> Path:
    key = re.sub(r"[^A-Za-z0-9_.-]+", "_", rec.get("key") or rec.get("title") or "question")
    return out_dir / "text" / f"{key}.txt"


def pdf_path_for(out_dir: Path, rec: dict[str, Any]) -> Path | None:
    raw = rec.get("pdf_path")
    if not raw:
        return None
    path = out_dir / raw
    return path if path.exists() else None


def excerpt(text: str, max_len: int = 280) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


def parse_corpus(topic: TopicProfile, out_dir: Path, *, refresh_text: bool = False) -> list[dict[str, Any]]:
    manifest = out_dir / "manifest.jsonl"
    records = read_jsonl(manifest)
    analysis: list[dict[str, Any]] = []
    log_path = out_dir / "parse.log"
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, rec in enumerate(records, 1):
        if i % 50 == 0:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"[{now()}] parsed {i}/{len(records)}\n")
        tpath = text_path_for(out_dir, rec)
        text = ""
        if tpath.exists() and not refresh_text:
            text = tpath.read_text(encoding="utf-8", errors="ignore")
        if not text.strip():
            pdf = pdf_path_for(out_dir, rec)
            if pdf:
                text = extract_pdf_text(pdf)
            if not text.strip():
                text = " ".join(
                    filter(
                        None,
                        [
                            clean_htmlish(rec.get("title")),
                            clean_htmlish(rec.get("question_text")),
                            clean_htmlish(rec.get("answer_text")),
                        ],
                    )
                )
            if text.strip():
                tpath.parent.mkdir(parents=True, exist_ok=True)
                tpath.write_text(text, encoding="utf-8")
        semantic = topic.classify(
            rec.get("title"),
            rec.get("question_text"),
            rec.get("answer_text"),
            rec.get("found_via_query"),
            text,
        )
        analysis.append(
            {
                **rec,
                "tags": semantic["tags"],
                "matches": semantic["matches"],
                "score": semantic["score"],
                "text_len": len(text),
                "excerpt": excerpt(text or clean_htmlish(rec.get("title"))),
            }
        )
    (out_dir / "analysis.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in analysis) + ("\n" if analysis else ""),
        encoding="utf-8",
    )
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{now()}] wrote analysis records={len(analysis)}\n")
    return analysis
