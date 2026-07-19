import unittest
from types import SimpleNamespace

from commoner_analyse.roster import (
    RosterExtractor,
    RosterMember,
    assign_sections,
    composition_window,
)


def _ext(cls, text, start=None, end=None):
    interval = None if start is None else SimpleNamespace(start_pos=start, end_pos=end)
    return SimpleNamespace(
        extraction_class=cls, extraction_text=text, char_interval=interval
    )


class CompositionWindowTests(unittest.TestCase):
    def test_anchors_on_last_heading_not_toc(self):
        text = (
            "CONTENTS\n1. COMPOSITION OF THE COMMITTEE\n2. REPORT\n"
            + "filler\n" * 50
            + "COMPOSITION OF THE COMMITTEE\n1.\nShri A\nSECRETARIAT\nShri B, Director\n"
        )
        window = composition_window(text)
        self.assertTrue(window.startswith("COMPOSITION OF THE COMMITTEE\n1.\nShri A"))

    def test_missing_heading_raises(self):
        with self.assertRaises(ValueError):
            composition_window("no roster here")

    def test_no_secretariat_uses_fallback_length(self):
        text = "COMPOSITION OF THE COMMITTEE\n" + "x" * 10000
        self.assertEqual(len(composition_window(text, fallback=4000)), 4000)


class AssignSectionsTests(unittest.TestCase):
    def test_nearest_preceding_header_wins(self):
        window = "COMPOSITION\nRAJYA SABHA\nShri A\nLOK SABHA\nShri B\nSECRETARIAT\nShri C"
        members = [
            RosterMember("Shri A", window.index("Shri A"), 0, None),
            RosterMember("Shri B", window.index("Shri B"), 0, None),
            RosterMember("Shri C", window.index("Shri C"), 0, None),
        ]
        assign_sections(members, window)
        self.assertEqual([m.section for m in members],
                         ["RAJYA SABHA", "LOK SABHA", "SECRETARIAT"])

    def test_headerless_roster_gets_default_section(self):
        window = "COMPOSITION\n1.\nShri A\n2.\nShri B"
        members = [RosterMember("Shri A", 12, 18, None)]
        assign_sections(members, window, default_section="RAJYA SABHA")
        self.assertEqual(members[0].section, "RAJYA SABHA")


class RosterExtractorTests(unittest.TestCase):
    def test_grounded_members_kept_ungrounded_dropped_vacancies_counted(self):
        window_text = "COMPOSITION OF THE COMMITTEE\nRAJYA SABHA\nShri Real Member\nVacant\n"

        def fake(window):
            self.assertIn("Shri Real Member", window)
            return [
                _ext("member", "Shri Real Member",
                     window.index("Shri Real Member"), window.index("Shri Real Member") + 16),
                _ext("member", "Shri Leaked Example"),
                _ext("vacancy", "Vacant", window.index("Vacant"), window.index("Vacant") + 6),
                _ext("member", "Article 1", 0, 9),
            ]

        result = RosterExtractor(extract_fn=fake).extract(window_text)
        self.assertEqual([m.name for m in result.members], ["Shri Real Member"])
        self.assertEqual(result.members[0].section, "RAJYA SABHA")
        self.assertEqual(result.vacancies, 1)
        self.assertEqual(result.dropped_ungrounded, 1)
        self.assertEqual(result.dropped_nonmember, 1)


if __name__ == "__main__":
    unittest.main()
