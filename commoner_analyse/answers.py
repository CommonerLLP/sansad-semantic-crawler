"""Answer extraction — delegated to commoner-probe (single source of truth).

This module used to carry a byte-identical copy of the PDF answer/ATR/DFG
extraction logic. It now re-exports that implementation from
``commoner_probe.answers`` so the extraction code lives in exactly one place
(the published ``commoner-probe`` package). The public surface (functions,
dataclasses, the version constant, and the test-referenced parse helpers) is
preserved so existing ``from commoner_analyse.answers import ...``
callers keep working unchanged.
"""

from __future__ import annotations

from commoner_probe.answers import (  # noqa: F401  (re-export)
    EXTRACTOR_VERSION,
    AtrExtraction,
    DfgExtraction,
    ExtractionStats,
    QaExtraction,
    _parse_answer_minister_and_body,
    _parse_question_stem_and_body,
    _parse_question_subject,
    extract_answers,
    extract_pdf_text,
    read_jsonl,
    split_atr,
    split_dfg,
    split_qa,
)

__all__ = [
    "EXTRACTOR_VERSION",
    "AtrExtraction",
    "DfgExtraction",
    "ExtractionStats",
    "QaExtraction",
    "_parse_answer_minister_and_body",
    "_parse_question_stem_and_body",
    "_parse_question_subject",
    "extract_answers",
    "extract_pdf_text",
    "read_jsonl",
    "split_atr",
    "split_dfg",
    "split_qa",
]
