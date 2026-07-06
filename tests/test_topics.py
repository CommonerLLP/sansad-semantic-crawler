from pathlib import Path
import unittest

from commoner_analyse.sansad import stable_key
from commoner_analyse.topics import load_topic


ROOT = Path(__file__).resolve().parents[1]


class TopicTests(unittest.TestCase):
    def test_library_profile_classifies_public_library(self):
        topic = load_topic(ROOT / "examples" / "topics" / "libraries.json")
        result = topic.classify("National Mission on Libraries and public libraries")
        self.assertIn("nml", result["tags"])
        self.assertIn("public_library", result["tags"])
        self.assertGreater(result["score"], 0)

    def test_stable_key_normalizes_house_type_number_date(self):
        self.assertEqual(stable_key("Lok Sabha", "Unstarred", "178.0", "2024-11-25"), "LS|U|178|2024-11-25")
        self.assertEqual(stable_key("Rajya Sabha", "STARRED", "42", "2025-02-03"), "RS|S|42|2025-02-03")


if __name__ == "__main__":
    unittest.main()
