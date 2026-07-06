import json
import tempfile
import unittest
from pathlib import Path

from commoner_analyse.manifest_contract import (
    iter_manifest_records,
    normalize_manifest_record,
)
from commoner_analyse.textparse import parse_corpus
from commoner_analyse.topics import load_topic


ROOT = Path(__file__).resolve().parents[1]
TOPIC = ROOT / "examples" / "topics" / "libraries.json"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _old_local_row() -> dict:
    return {
        "key": "LS|U|42|2026-01-01",
        "kind": "qa",
        "house": "Lok Sabha",
        "title": "National Mission on Libraries and public libraries",
        "date": "2026-01-01",
        "qtype": "Unstarred",
        "qno": "42",
        "ministry": "Culture",
        "askers": ["MP One"],
        "source": "elibrary.sansad.in",
        "found_via_query": "public library",
        "crawled_at": "2026-06-01T10:00:00",
        "tags": ["legacy_tag"],
        "matches": {"legacy_tag": ["legacy phrase"]},
        "score": 1.0,
        "classifier": "regex",
    }


def _commoner_probe_qa_row() -> dict:
    return {
        "key": "LS|U|43|2026-01-02",
        "run_id": "f" * 32,
        "kind": "qa",
        "house": "Lok Sabha",
        "uuid": "uuid-43",
        "handle": "123456789/43",
        "title": "National Mission on Libraries and public libraries",
        "date": "2026-01-02",
        "qtype": "Unstarred",
        "qno": "43",
        "session": "18",
        "loksabhanumber": "18",
        "ministry": "Culture",
        "askers": ["MP Two"],
        "asker_details": [
            {
                "name": "MP Two",
                "party": None,
                "party_name": None,
                "house": "Lok Sabha",
            }
        ],
        "asker_entity_ids": [None],
        "responder_entity_id": None,
        "responder_role_at_event": None,
        "uri": "https://eparlib.nic.in/handle/123456789/43",
        "source": "elibrary.sansad.in",
        "found_via_group": "libraries",
        "found_via_query": "public library",
        "probed_at": "2026-06-02T12:00:00",
        "language_classified": ["en"],
        "question_text": "Will the Minister of Culture be pleased to state public library plans?",
        "answer_text": "The National Mission on Libraries supports public libraries.",
    }


class ManifestContractTests(unittest.TestCase):
    def test_old_local_manifest_row_keeps_semantic_fields_and_crawl_contract(self):
        row = normalize_manifest_record(_old_local_row(), acquisition_log="crawl.log")

        self.assertEqual(row["acquisition_source"], "commoner-analyse")
        self.assertEqual(row["acquired_at"], "2026-06-01T10:00:00")
        self.assertEqual(row["acquisition_log"], "crawl.log")
        self.assertEqual(row["tags"], ["legacy_tag"])
        self.assertEqual(row["matches"], {"legacy_tag": ["legacy phrase"]})
        self.assertEqual(row["classifier"], "regex")

    def test_commoner_probe_manifest_row_gets_analysis_defaults_and_probe_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "probe.log").write_text("[2026-06-02T12:00:00] done\n", encoding="utf-8")
            _write_jsonl(out / "manifest.jsonl", [_commoner_probe_qa_row()])

            rows = list(iter_manifest_records(out / "manifest.jsonl"))

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["acquisition_source"], "commoner-probe")
        self.assertEqual(row["acquired_at"], "2026-06-02T12:00:00")
        self.assertEqual(row["acquisition_log"], "probe.log")
        self.assertEqual(row["tags"], [])
        self.assertEqual(row["matches"], {})
        self.assertEqual(row["score"], 0)
        self.assertEqual(row["classifier"], "")

    def test_parse_corpus_accepts_old_local_manifest_with_semantic_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "crawl.log").write_text("[2026-06-01T10:00:00] done\n", encoding="utf-8")
            _write_jsonl(out / "manifest.jsonl", [_old_local_row()])

            parsed = parse_corpus(load_topic(TOPIC), out)

        self.assertEqual(len(parsed), 1)
        row = parsed[0]
        self.assertEqual(row["acquisition_source"], "commoner-analyse")
        self.assertEqual(row["acquired_at"], "2026-06-01T10:00:00")
        self.assertEqual(row["acquisition_log"], "crawl.log")
        self.assertEqual(row["classifier"], "regex")
        self.assertIn("nml", row["tags"])

    def test_parse_corpus_accepts_commoner_probe_manifest_with_schema_valid_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "probe.log").write_text("[2026-06-02T12:00:00] done\n", encoding="utf-8")
            _write_jsonl(out / "manifest.jsonl", [_commoner_probe_qa_row()])

            parsed = parse_corpus(load_topic(TOPIC), out)

        self.assertEqual(len(parsed), 1)
        row = parsed[0]
        self.assertEqual(row["acquisition_source"], "commoner-probe")
        self.assertEqual(row["acquired_at"], "2026-06-02T12:00:00")
        self.assertEqual(row["acquisition_log"], "probe.log")
        self.assertEqual(row["probed_at"], "2026-06-02T12:00:00")
        self.assertEqual(row["classifier"], "regex")
        self.assertIn("nml", row["tags"])


if __name__ == "__main__":
    unittest.main()
