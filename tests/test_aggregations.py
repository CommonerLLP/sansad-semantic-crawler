"""Tests for the per-MP and per-ministry aggregation summaries."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sansad_semantic_crawler.aggregations import (
    AGGREGATION_VERSION,
    write_ministry_summary,
    write_mp_summary,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )


class MpSummaryTests(unittest.TestCase):

    def test_basic_aggregation_per_mp(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {
                    "key": "k1", "kind": "qa", "ministry": "FINANCE",
                    "house": "Lok Sabha",
                    "asker_details": [{"name": "Aarav Sharma", "party": "NCP", "state": "Maharashtra"}],
                    "asker_entity_ids": ["PERSON_aaa_aarav_sharma"],
                    "askers": ["Aarav Sharma"],
                },
                {
                    "key": "k2", "kind": "qa", "ministry": "RURAL DEVELOPMENT",
                    "house": "Lok Sabha",
                    "asker_details": [{"name": "Aarav Sharma", "party": "NCP", "state": "Maharashtra"}],
                    "asker_entity_ids": ["PERSON_aaa_aarav_sharma"],
                    "askers": ["Aarav Sharma"],
                },
                {
                    "key": "k3", "kind": "qa", "ministry": "FINANCE",
                    "house": "Lok Sabha",
                    "asker_details": [{"name": "Priya Iyer", "party": "AITC", "state": "West Bengal"}],
                    "asker_entity_ids": ["PERSON_bbb_priya_iyer"],
                    "askers": ["Priya Iyer"],
                },
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [
                {"key": "k1", "label": "ACCEPTED", "channel": "qa"},
                {"key": "k2", "label": "DEFLECTED", "channel": "qa"},
                {"key": "k3", "label": "DATA_WITHHELD", "channel": "qa"},
            ])

            stats = write_mp_summary(out, log_fn=lambda *_: None)
            rows = [json.loads(l) for l in (out / "mp_summary.jsonl").read_text().splitlines()]

        self.assertEqual(stats.persons_emitted, 2)
        by_id = {r["entity_id"]: r for r in rows}
        aarav = by_id["PERSON_aaa_aarav_sharma"]
        self.assertEqual(aarav["questions_asked"], 2)
        self.assertEqual(aarav["ministries_asked"], {"FINANCE": 1, "RURAL DEVELOPMENT": 1})
        self.assertEqual(aarav["party"], "NCP")
        self.assertEqual(aarav["state"], "Maharashtra")
        self.assertEqual(aarav["substantive_count"], 1)  # ACCEPTED
        self.assertEqual(aarav["evasive_count"], 1)      # DEFLECTED
        self.assertAlmostEqual(aarav["evasion_rate_classified"], 0.5)
        self.assertEqual(aarav["method"], AGGREGATION_VERSION)

        priya = by_id["PERSON_bbb_priya_iyer"]
        self.assertEqual(priya["questions_asked"], 1)
        self.assertEqual(priya["evasive_count"], 1)
        self.assertEqual(priya["evasion_rate_classified"], 1.0)

    def test_committee_records_excluded_from_mp_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                # A committee report — has no single asker, must be skipped.
                {
                    "key": "LS|finance|33|18", "kind": "committee_report",
                    "committee_slug": "finance", "report_type": "action_taken",
                },
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [])
            stats = write_mp_summary(out, log_fn=lambda *_: None)
        self.assertEqual(stats.persons_emitted, 0)

    def test_evasion_rate_none_when_only_unclassified(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {
                    "key": "k1", "kind": "qa", "ministry": "X",
                    "asker_details": [{"name": "A", "party": "P"}],
                    "asker_entity_ids": ["PERSON_aaa"],
                    "askers": ["A"],
                },
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [
                {"key": "k1", "label": "UNCLASSIFIED"},
            ])
            write_mp_summary(out, log_fn=lambda *_: None)
            row = json.loads((out / "mp_summary.jsonl").read_text().splitlines()[0])
        self.assertIsNone(row["evasion_rate_classified"])
        self.assertEqual(row["unclassified_count"], 1)

    def test_name_fallback_when_no_entity_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {
                    "key": "k1", "kind": "qa", "ministry": "X",
                    "askers": ["Some MP"],  # no asker_entity_ids
                },
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [
                {"key": "k1", "label": "ACCEPTED"},
            ])
            stats = write_mp_summary(out, log_fn=lambda *_: None)
            row = json.loads((out / "mp_summary.jsonl").read_text().splitlines()[0])
        self.assertEqual(stats.persons_emitted, 1)
        self.assertIsNone(row["entity_id"])
        self.assertTrue(row["primary_key"].startswith("name:"))
        self.assertIn("Some MP", row["names_seen"])

    def test_topic_hash_in_each_row_when_topic_path_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            topic_path = out / "topic.json"
            topic_path.write_text(json.dumps({"name": "test"}), encoding="utf-8")
            _write_jsonl(out / "manifest.jsonl", [
                {
                    "key": "k1", "kind": "qa", "ministry": "X",
                    "asker_details": [{"name": "A"}],
                    "asker_entity_ids": ["PERSON_aaa"],
                    "askers": ["A"],
                },
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [
                {"key": "k1", "label": "ACCEPTED"},
            ])
            write_mp_summary(out, topic_profile_path=topic_path, log_fn=lambda *_: None)
            row = json.loads((out / "mp_summary.jsonl").read_text().splitlines()[0])
        self.assertTrue(row["topic_hash"].startswith("sha256:"))


class MinistrySummaryTests(unittest.TestCase):

    def test_qa_aggregation_per_ministry(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {"key": "k1", "kind": "qa", "ministry": "FINANCE", "asker_details": [{"name": "A"}], "askers": ["A"]},
                {"key": "k2", "kind": "qa", "ministry": "FINANCE", "asker_details": [{"name": "B"}], "askers": ["B"]},
                {"key": "k3", "kind": "qa", "ministry": "FINANCE", "asker_details": [{"name": "C"}], "askers": ["C"]},
                {"key": "k4", "kind": "qa", "ministry": "TRIBAL AFFAIRS", "asker_details": [{"name": "D"}], "askers": ["D"]},
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [
                {"key": "k1", "label": "ACCEPTED", "passive_ratio": 0.0, "agent_named": True},
                {"key": "k2", "label": "DEFLECTED", "passive_ratio": 1.0, "agent_named": False},
                {"key": "k3", "label": "SUBSTITUTED", "passive_ratio": 0.5, "agent_named": True},
                {"key": "k4", "label": "DATA_WITHHELD", "passive_ratio": 1.0, "agent_named": False},
            ])
            stats = write_ministry_summary(out, log_fn=lambda *_: None)
            rows = [json.loads(l) for l in (out / "ministry_summary_qa.jsonl").read_text().splitlines()]

        self.assertEqual(stats.qa_groups_emitted, 2)
        by_min = {r["ministry"]: r for r in rows}
        finance = by_min["FINANCE"]
        self.assertEqual(finance["records_total"], 3)
        self.assertEqual(finance["substantive_count"], 1)  # ACCEPTED
        self.assertEqual(finance["evasive_count"], 2)      # DEFLECTED + SUBSTITUTED
        self.assertAlmostEqual(finance["evasion_rate_classified"], 2 / 3, places=3)
        # per_evasion_label_share — half-and-half DEFLECTED / SUBSTITUTED
        self.assertAlmostEqual(finance["per_evasion_label_share"]["DEFLECTED"], 0.5)
        self.assertAlmostEqual(finance["per_evasion_label_share"]["SUBSTITUTED"], 0.5)
        self.assertAlmostEqual(finance["mean_passive_ratio"], 0.5)
        self.assertAlmostEqual(finance["agent_named_rate"], 2 / 3, places=3)

    def test_committee_aggregation_with_rejected_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {
                    "key": "LS|finance|33|18", "kind": "committee_report",
                    "house": "Lok Sabha", "committee_slug": "finance",
                    "report_type": "action_taken",
                },
                {
                    "key": "LS|finance|34|18", "kind": "committee_report",
                    "house": "Lok Sabha", "committee_slug": "finance",
                    "report_type": "action_taken",
                },
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [
                {"key": "LS|finance|33|18", "label": "REJECTED"},
                {"key": "LS|finance|34|18", "label": "ACCEPTED"},
            ])
            write_ministry_summary(out, log_fn=lambda *_: None)
            rows = [json.loads(l) for l in (out / "ministry_summary_committee.jsonl").read_text().splitlines()]

        self.assertEqual(len(rows), 1)
        finance = rows[0]
        self.assertEqual(finance["committee_slug"], "finance")
        self.assertEqual(finance["house"], "ls")
        self.assertEqual(finance["records_total"], 2)
        # The REJECTED row should be itemised for downstream use.
        self.assertEqual(finance["rejected_recommendation_keys"], ["LS|finance|33|18"])

    def test_qa_and_committee_outputs_are_separate_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {"key": "qak", "kind": "qa", "ministry": "X", "askers": ["Y"]},
                {"key": "cmk", "kind": "committee_report", "house": "Lok Sabha",
                 "committee_slug": "finance", "report_type": "action_taken"},
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [])
            write_ministry_summary(out, log_fn=lambda *_: None)
            # Assertions must run INSIDE the TemporaryDirectory context;
            # outside it the dir is cleaned up and `out` no longer exists.
            self.assertTrue((out / "ministry_summary_qa.jsonl").exists())
            self.assertTrue((out / "ministry_summary_committee.jsonl").exists())

    def test_unclassified_only_evasion_rate_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {"key": "k1", "kind": "qa", "ministry": "X", "askers": ["A"]},
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [
                {"key": "k1", "label": "UNCLASSIFIED"},
            ])
            write_ministry_summary(out, log_fn=lambda *_: None)
            row = json.loads((out / "ministry_summary_qa.jsonl").read_text().splitlines()[0])
        self.assertIsNone(row["evasion_rate_classified"])
        self.assertEqual(row["records_classified"], 0)


if __name__ == "__main__":
    unittest.main()
