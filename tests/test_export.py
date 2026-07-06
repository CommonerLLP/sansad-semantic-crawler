"""Tests for corpus-wide export: discourse summary, ministry rollup, glossary."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from commoner_analyse.discourse import DISCOURSE_LABEL_DESCRIPTIONS
from commoner_analyse.export import (
    build_discourse_summary,
    build_glossary,
    build_ministry_discourse,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class DiscourseSummaryTests(unittest.TestCase):

    def test_returns_none_when_analysis_discourse_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(build_discourse_summary(Path(tmp)))

    def test_counts_previously_unclassified_v2_labels_as_evasive(self):
        # Regression test: CONSTITUTIONAL_DEFAULT, FEDERAL_DEFLECTION,
        # STRUCTURAL_REFUSAL, and REPRESENTATIONAL_SILENCE (the
        # "Instrumented Discourse Tier v2" labels) were missing from
        # aggregations._EVASIVE, so every evasion rate silently undercounted
        # them as unclassified. Fixed 2026-07-06.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [{"key": f"k{i}"} for i in range(4)])
            _write_jsonl(out / "analysis_discourse.jsonl", [
                {"key": "k1", "label": "CONSTITUTIONAL_DEFAULT"},
                {"key": "k2", "label": "FEDERAL_DEFLECTION"},
                {"key": "k3", "label": "ACCEPTED"},
                {"key": "k4", "label": "REJECTED"},
            ])
            summary = build_discourse_summary(out)
            self.assertEqual(summary["evasiveCount"], 2)
            self.assertEqual(summary["substantiveCount"], 2)
            self.assertEqual(summary["responsesClassified"], 4)
            self.assertAlmostEqual(summary["evasionRateClassified"], 0.5)

    def test_evasion_rate_none_when_nothing_classified(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [{"key": "k1"}])
            _write_jsonl(out / "analysis_discourse.jsonl", [
                {"key": "k1", "label": "UNCLASSIFIED"},
            ])
            summary = build_discourse_summary(out)
            self.assertIsNone(summary["evasionRateClassified"])


class MinistryDiscourseTests(unittest.TestCase):

    def test_returns_none_when_ministry_summary_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(build_ministry_discourse(Path(tmp)))

    def test_reshapes_and_sorts_by_records_total_desc(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "ministry_summary_qa.jsonl", [
                {"ministry": "SMALL", "records_total": 2, "evasion_rate_classified": 0.5},
                {"ministry": "BIG", "records_total": 10, "evasion_rate_classified": 0.8},
            ])
            rows = build_ministry_discourse(out)
            self.assertEqual([r["ministry"] for r in rows], ["BIG", "SMALL"])
            self.assertEqual(rows[0]["recordsTotal"], 10)
            self.assertEqual(rows[0]["evasionRateClassified"], 0.8)


class GlossaryTests(unittest.TestCase):

    def test_every_taxonomy_label_present_and_classified(self):
        glossary = build_glossary()
        labels = {row["label"]: row for row in glossary["labels"]}
        self.assertEqual(set(labels), set(DISCOURSE_LABEL_DESCRIPTIONS))
        for label, row in labels.items():
            self.assertIn(row["function"], {"substantive", "evasive", "unclassified"})
            self.assertEqual(row["description"], DISCOURSE_LABEL_DESCRIPTIONS[label])

    def test_v2_tier_labels_classified_as_evasive_not_unclassified(self):
        glossary = build_glossary()
        labels = {row["label"]: row["function"] for row in glossary["labels"]}
        for label in (
            "CONSTITUTIONAL_DEFAULT",
            "FEDERAL_DEFLECTION",
            "STRUCTURAL_REFUSAL",
            "REPRESENTATIONAL_SILENCE",
        ):
            self.assertEqual(labels[label], "evasive")


if __name__ == "__main__":
    unittest.main()
