"""Pilot: grounded committee-roster extraction with langextract over local Ollama.

Benchmark question: can langextract + a <=3B local model extract the
"Composition of the Committee" roster from RS standing-committee report PDFs
with char-level source grounding, surviving glued names, vacancies, and
footnotes? Outputs JSONL + HTML review pages for human verification.

Usage:
    .venv/bin/python scripts/langextract_pilot.py data/exam-paper-leaks-committees/pdfs/rs/education_377.pdf [more.pdf ...]
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import langextract as lx

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "langextract-pilot"

MODEL_ID = "qwen2.5:3b"
MODEL_URL = "http://localhost:11434"

PROMPT = """\
Extract every person listed in this parliamentary committee composition.
Use the exact name text as it appears (do not fix spacing or spelling).
For each person record their house section (RAJYA SABHA, LOK SABHA, or
SECRETARIAT) and role (Chairman, Member, or the secretariat designation).
Also extract vacancy markers ('#' entries) as class 'vacancy'.
Do not invent people who are not in the text."""

EXAMPLE = lx.data.ExampleData(
    text=(
        "COMMITTEE ON EXAMPLE AFFAIRS\n(Constituted w.e.f. 1st January, 2025)\n"
        "1.\nShri Example Chairperson\n\nChairman\nRAJYA SABHA\n"
        "2.\nDr.GluedNameExample\n3.\n#\nLOK SABHA\n4.\nSmt. Lok Member\n"
        "SECRETARIAT\nShri Officer One, Joint Secretary\n"
    ),
    extractions=[
        lx.data.Extraction(
            extraction_class="member",
            extraction_text="Shri Example Chairperson",
            attributes={"house": "RAJYA SABHA", "role": "Chairman"},
        ),
        lx.data.Extraction(
            extraction_class="member",
            extraction_text="Dr.GluedNameExample",
            attributes={"house": "RAJYA SABHA", "role": "Member"},
        ),
        lx.data.Extraction(
            extraction_class="vacancy",
            extraction_text="#",
            attributes={"house": "RAJYA SABHA"},
        ),
        lx.data.Extraction(
            extraction_class="member",
            extraction_text="Smt. Lok Member",
            attributes={"house": "LOK SABHA", "role": "Member"},
        ),
        lx.data.Extraction(
            extraction_class="member",
            extraction_text="Shri Officer One",
            attributes={"house": "SECRETARIAT", "role": "Joint Secretary"},
        ),
    ],
)


def composition_window(pdf: Path) -> str:
    """pdftotext the PDF and slice the composition roster region."""
    text = subprocess.run(
        ["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True
    ).stdout
    # The first COMPOSITION hit is usually the table of contents; anchor on
    # the last one, which is the roster section itself.
    start = text.rfind("COMPOSITION OF THE COMMITTEE")
    if start == -1:
        raise ValueError(f"no COMPOSITION heading in {pdf.name}")
    end_match = re.search(r"SECRETARIAT", text[start:])
    end = start + end_match.end() + 800 if end_match else start + 4000
    return text[start:end]


def main(pdf_paths: list[str]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for raw in pdf_paths:
        pdf = Path(raw)
        window = composition_window(pdf)
        print(f"== {pdf.name}: {len(window)} chars")
        result = lx.extract(
            text_or_documents=window,
            prompt_description=PROMPT,
            examples=[EXAMPLE],
            model_id=MODEL_ID,
            model_url=MODEL_URL,
            fence_output=False,
            use_schema_constraints=False,
            language_model_params={"timeout": 600},
        )
        grounded = sum(1 for e in result.extractions if e.char_interval is not None)
        print(f"   {len(result.extractions)} extractions, {grounded} grounded")
        for e in result.extractions:
            iv = e.char_interval
            span = f"[{iv.start_pos}:{iv.end_pos}]" if iv else "[UNGROUNDED]"
            print(f"   {e.extraction_class:9s} {span:14s} {e.extraction_text!r} {e.attributes}")
        stem = pdf.stem
        lx.io.save_annotated_documents(
            [result], output_name=f"{stem}.jsonl", output_dir=str(OUT_DIR)
        )
        html = lx.visualize(str(OUT_DIR / f"{stem}.jsonl"))
        (OUT_DIR / f"{stem}.html").write_text(
            html.data if hasattr(html, "data") else html
        )
        print(f"   wrote {OUT_DIR / (stem + '.jsonl')} and .html")


if __name__ == "__main__":
    main(sys.argv[1:])
