import json
import tempfile
import unittest
from pathlib import Path

from commoner_analyse.textparse import parse_corpus
from commoner_analyse.topics import load_topic


ROOT = Path(__file__).resolve().parents[1]


class TextParseTests(unittest.TestCase):
    def test_parse_corpus_preserves_classifier_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rows = [
                {
                    "key": f"LS|U|{i}|2026-01-0{i}",
                    "house": "Lok Sabha",
                    "title": "National Mission on Libraries and public libraries",
                    "date": f"2026-01-0{i}",
                    "found_via_query": "public library",
                }
                for i in range(1, 6)
            ]
            (out / "manifest.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )
            topic = load_topic(ROOT / "examples" / "topics" / "libraries.json")
            parsed = parse_corpus(topic, out)
        self.assertEqual(len(parsed), 5)
        self.assertEqual(parsed[0]["classifier"], "regex")
        self.assertIn("nml", parsed[0]["tags"])


if __name__ == "__main__":
    unittest.main()
