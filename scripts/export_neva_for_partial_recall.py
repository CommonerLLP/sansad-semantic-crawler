#!/usr/bin/env python3
# Converts neva/gujarat/questions.jsonl → markdown files for partial-recall folder indexing.
# Run: .venv/bin/python3.14 scripts/export_neva_for_partial_recall.py
# Re-run after crawl completes — idempotent (only writes new/changed files).

import json
import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JSONL_PATH = REPO_ROOT / "data" / "neva" / "gujarat" / "questions.jsonl"
EXPORT_DIR = REPO_ROOT / "data" / "neva" / "gujarat" / "md_export"


def record_to_md(r: dict) -> str:
    subject = (r.get("subject") or "").strip()
    question_text = (r.get("question_text") or "").strip()
    ministry = (r.get("ministry") or "").strip()
    member = (r.get("member_name") or "").strip()
    constituency = (r.get("constituency") or "").strip()
    session_no = r.get("session_no", "")
    assembly_no = r.get("assembly_no", "")
    q_no = r.get("question_number", "")
    date_id = r.get("session_date_id", "")
    has_pdf = bool(r.get("pdf_path"))

    lines = [
        "---",
        f'key: "{r["key"]}"',
        f'source: "neva-gujarat"',
        f'assembly: {assembly_no}',
        f'session: {session_no}',
        f'session_date_id: {date_id}',
        f'question_number: "{q_no}"',
        f'ministry: "{ministry}"',
        f'member: "{member}"',
        f'constituency: "{constituency}"',
        f'has_answer_pdf: {str(has_pdf).lower()}',
        "---",
        "",
    ]

    if subject:
        lines.append(f"# {subject}")
        lines.append("")

    if ministry:
        lines.append(f"Ministry: {ministry}")
    if member:
        lines.append(f"Member: {member} ({constituency})")
    lines.append(f"Session {session_no}, Question {q_no}")
    lines.append("")

    if question_text:
        lines.append(question_text)

    return "\n".join(lines)


def main() -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    records = [
        json.loads(line)
        for line in JSONL_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    written = 0
    skipped = 0
    for r in records:
        key = r["key"].replace("|", "_").replace("/", "_")
        dest = EXPORT_DIR / f"{key}.md"
        content = record_to_md(r)
        digest = hashlib.md5(content.encode()).hexdigest()
        digest_file = dest.with_suffix(".md.digest")

        if dest.exists() and digest_file.exists() and digest_file.read_text().strip() == digest:
            skipped += 1
            continue

        dest.write_text(content, encoding="utf-8")
        digest_file.write_text(digest, encoding="utf-8")
        written += 1

    print(f"Export complete: {written} written, {skipped} unchanged → {EXPORT_DIR}")
    print(f"Total files: {len(records)}")


if __name__ == "__main__":
    main()
