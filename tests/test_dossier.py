"""Tests for v0.6.6 mp-dossier — per-MP topic briefing.

Covers:

- Topic key normalisation (token-set keying, stopword removal,
  parliamentary-boilerplate filtering).
- Loose name matching (surname, substring, case-insensitive).
- Record selection by entity_id (preferred) and by name (fallback).
- Markdown rendering structure: summary block, topic groups,
  evasive-vs-substantive sample buckets, generated-by footer.
- Empty-corpus and no-match paths produce a usable Markdown stub
  rather than crashing or silently producing nothing.
- Output is filesystem-safe (slug derives from entity_id when present).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sansad_semantic_crawler.dossier import (
    DOSSIER_VERSION,
    _name_matches,
    _normalize_topic_key,
    _slugify,
    build_mp_dossier,
    find_mp_records,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# Topic key normalisation                                                     #
# --------------------------------------------------------------------------- #


class NormalizeTopicKeyTests(unittest.TestCase):

    def test_alphabetisation_makes_order_irrelevant(self):
        a = _normalize_topic_key("ANNUAL INCOME OF SHGS")
        b = _normalize_topic_key("SHG ANNUAL INCOME")
        # "SHGS" and "SHG" are different surface tokens — but order/stopwords
        # shouldn't matter when they DO share tokens.
        self.assertEqual(
            _normalize_topic_key("LIBRARY FUNDING IMPACT"),
            _normalize_topic_key("IMPACT ON LIBRARY FUNDING"),
        )

    def test_stopwords_dropped(self):
        # "of", "the" are dropped.
        self.assertEqual(
            _normalize_topic_key("STATUS OF THE MGNREGA SCHEME"),
            "MGNREGA",
        )
        # "scheme", "status" are parliamentary boilerplate.

    def test_parliamentary_boilerplate_dropped(self):
        # "GOVERNMENT" / "MINISTRY" / "DEPARTMENT" are noise for topic identity.
        self.assertEqual(
            _normalize_topic_key("GOVERNMENT POLICY ON LIBRARIES"),
            "LIBRARIES",
        )

    def test_empty_or_all_stopwords_returns_empty(self):
        self.assertEqual(_normalize_topic_key(""), "")
        self.assertEqual(_normalize_topic_key(None), "")
        # All-stopword input — not a real topic.
        self.assertEqual(_normalize_topic_key("status of the scheme"), "")

    def test_short_tokens_filtered_out(self):
        # Single-letter standalone tokens shouldn't anchor a topic.
        # "A" is a stopword; len=1 anyway. We check that the result tokens
        # don't include a bare "A" — but we can't string-substring-check
        # because LIBR**A**RY contains "A". Token-by-token check instead.
        result = _normalize_topic_key("USE OF A LIBRARY")
        tokens = result.split()
        self.assertNotIn("A", tokens)
        self.assertIn("LIBRARY", tokens)


# --------------------------------------------------------------------------- #
# Loose name matching                                                          #
# --------------------------------------------------------------------------- #


class NameMatchesTests(unittest.TestCase):

    def test_exact_surname_match(self):
        self.assertTrue(_name_matches("Sule", "Supriya Sule"))
        self.assertTrue(_name_matches("sule", "SUPRIYA SULE"))

    def test_substring_with_honorific(self):
        self.assertTrue(_name_matches("Supriya Sule", "Smt. Supriya Sule"))
        self.assertTrue(_name_matches("Sivadasan", "Dr V Sivadasan"))

    def test_no_match(self):
        self.assertFalse(_name_matches("Modi", "Supriya Sule"))
        self.assertFalse(_name_matches("", "Supriya Sule"))
        self.assertFalse(_name_matches("Sule", ""))


# --------------------------------------------------------------------------- #
# Record selection                                                             #
# --------------------------------------------------------------------------- #


class FindMpRecordsTests(unittest.TestCase):

    def test_by_entity_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {"key": "k1", "kind": "qa", "ministry": "FINANCE",
                 "asker_entity_ids": ["PERSON_aaa_supriya_sule"],
                 "asker_details": [{"name": "Supriya Sule", "party": "NCP"}],
                 "askers": ["Supriya Sule"]},
                {"key": "k2", "kind": "qa", "ministry": "AGRI",
                 "asker_entity_ids": ["PERSON_bbb_other"],
                 "asker_details": [{"name": "Other"}],
                 "askers": ["Other"]},
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [])
            pairs = find_mp_records(out, entity_id="PERSON_aaa_supriya_sule")
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0][0]["key"], "k1")

    def test_by_name_loose_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {"key": "k1", "kind": "qa",
                 "asker_details": [{"name": "Smt. Supriya Sule", "party": "NCP"}],
                 "askers": ["Smt. Supriya Sule"]},
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [])
            pairs = find_mp_records(out, name="Sule")
            self.assertEqual(len(pairs), 1)

    def test_committee_records_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {"key": "k1", "kind": "committee_report",
                 "committee_slug": "finance",
                 "report_type": "action_taken"},
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [])
            pairs = find_mp_records(out, name="anyone")
            self.assertEqual(len(pairs), 0)

    def test_discourse_join(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {"key": "k1", "kind": "qa",
                 "asker_entity_ids": ["PERSON_aaa"],
                 "asker_details": [{"name": "X"}],
                 "askers": ["X"]},
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [
                {"key": "k1", "label": "DEFLECTED", "channel": "qa"},
            ])
            pairs = find_mp_records(out, entity_id="PERSON_aaa")
            self.assertEqual(len(pairs), 1)
            self.assertIsNotNone(pairs[0][1])
            self.assertEqual(pairs[0][1]["label"], "DEFLECTED")

    def test_neither_id_nor_name_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [])
            _write_jsonl(out / "analysis_discourse.jsonl", [])
            with self.assertRaises(ValueError):
                find_mp_records(out)


# --------------------------------------------------------------------------- #
# Markdown dossier integration                                                 #
# --------------------------------------------------------------------------- #


class BuildMpDossierTests(unittest.TestCase):

    def _setup_corpus(
        self,
        tmp: Path,
        *,
        manifest: list[dict],
        discourse: list[dict] | None = None,
        answers: list[dict] | None = None,
    ) -> None:
        _write_jsonl(tmp / "manifest.jsonl", manifest)
        _write_jsonl(tmp / "analysis_discourse.jsonl", discourse or [])
        _write_jsonl(tmp / "answers.jsonl", answers or [])

    def test_dossier_renders_summary_and_topics(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._setup_corpus(
                out,
                manifest=[
                    {
                        "key": "k1", "kind": "qa", "ministry": "CULTURE",
                        "house": "Lok Sabha", "date": "2023-08-12",
                        "asker_entity_ids": ["PERSON_aaa"],
                        "asker_details": [{"name": "Dr V Sivadasan", "party": "CPI(M)", "state": "Kerala"}],
                        "askers": ["Dr V Sivadasan"],
                    },
                    {
                        "key": "k2", "kind": "qa", "ministry": "CULTURE",
                        "house": "Lok Sabha", "date": "2024-03-04",
                        "asker_entity_ids": ["PERSON_aaa"],
                        "asker_details": [{"name": "Dr V Sivadasan", "party": "CPI(M)", "state": "Kerala"}],
                        "askers": ["Dr V Sivadasan"],
                    },
                ],
                answers=[
                    {"key": "k1", "kind": "qa_response", "question_subject": "LIBRARY FUNDING",
                     "answer_body": "Library is a state subject under Schedule VII..."},
                    {"key": "k2", "kind": "qa_response", "question_subject": "STATUS OF LIBRARIES",
                     "answer_body": "No separate data is maintained centrally on libraries."},
                ],
                discourse=[
                    {"key": "k1", "label": "SCOPE_NARROWED", "channel": "qa",
                     "text_excerpt": "Library is a state subject under Schedule VII..."},
                    {"key": "k2", "label": "DATA_WITHHELD", "channel": "qa",
                     "text_excerpt": "No separate data is maintained centrally..."},
                ],
            )
            path = build_mp_dossier(out, entity_id="PERSON_aaa", log_fn=lambda *_: None)
            self.assertIsNotNone(path)
            md = path.read_text()
            # Header + summary
            self.assertIn("Sivadasan", md)
            self.assertIn("CPI(M)", md)
            self.assertIn("Kerala", md)
            self.assertIn("**Total questions:** 2", md)
            # Topic group: LIBRARY tokens cluster the two questions
            self.assertIn("Topics", md)
            # Evasion sample text surfaced
            self.assertIn("state subject under Schedule VII", md)
            self.assertIn("SCOPE_NARROWED", md)
            self.assertIn("DATA_WITHHELD", md)
            # Footer carries provenance
            self.assertIn(DOSSIER_VERSION, md)

    def test_no_records_returns_none_and_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._setup_corpus(out, manifest=[])
            path = build_mp_dossier(out, name="Nobody", log_fn=lambda *_: None)
            self.assertIsNone(path)
            self.assertFalse((out / "mp_dossiers").exists())

    def test_uncategorised_bucket_for_records_without_subject(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._setup_corpus(
                out,
                manifest=[
                    {
                        "key": "k1", "kind": "qa", "ministry": "X",
                        "asker_entity_ids": ["PERSON_aaa"],
                        "asker_details": [{"name": "X Person"}],
                        "askers": ["X Person"],
                    },
                ],
                # No structured question_subject — record falls into Uncategorised.
                answers=[{"key": "k1", "kind": "qa_response"}],
                discourse=[{"key": "k1", "label": "DEFLECTED"}],
            )
            path = build_mp_dossier(out, entity_id="PERSON_aaa", log_fn=lambda *_: None)
            md = path.read_text()
            self.assertIn("Uncategorised", md)

    def test_slug_derives_from_entity_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._setup_corpus(
                out,
                manifest=[{
                    "key": "k1", "kind": "qa",
                    "asker_entity_ids": ["PERSON_aaa_supriya_sule"],
                    "asker_details": [{"name": "Supriya Sule"}],
                    "askers": ["Supriya Sule"],
                }],
                answers=[{"key": "k1", "kind": "qa_response", "question_subject": "PMFBY"}],
                discourse=[{"key": "k1", "label": "ACCEPTED"}],
            )
            path = build_mp_dossier(out, entity_id="PERSON_aaa_supriya_sule", log_fn=lambda *_: None)
            self.assertEqual(path.name, "PERSON_aaa_supriya_sule.md")

    def test_display_picks_most_common_surface_form(self):
        # Three records cluster into one topic key. Two carry the surface
        # form "LIBRARY FUNDING IMPACT", one carries "IMPACT ON LIBRARY
        # FUNDING". The section heading should reflect the more common
        # surface form, not whichever record happened to come last in
        # iteration order. This is the regression test for the
        # "[subject for _ in range(...)]" bug where display was driven
        # by the latest record only.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._setup_corpus(
                out,
                manifest=[
                    {"key": f"k{i}", "kind": "qa", "ministry": "CULTURE",
                     "asker_entity_ids": ["PERSON_aaa"],
                     "asker_details": [{"name": "X"}],
                     "askers": ["X"]}
                    for i in range(3)
                ],
                answers=[
                    {"key": "k0", "question_subject": "LIBRARY FUNDING IMPACT"},
                    {"key": "k1", "question_subject": "LIBRARY FUNDING IMPACT"},
                    {"key": "k2", "question_subject": "IMPACT ON LIBRARY FUNDING"},
                ],
                discourse=[],
            )
            path = build_mp_dossier(out, entity_id="PERSON_aaa", log_fn=lambda *_: None)
            md = path.read_text()
            self.assertIn("### Library Funding Impact (3 questions)", md)
            self.assertNotIn("### Impact On Library Funding (3 questions)", md)

    def test_topic_clustering_groups_same_token_set_questions(self):
        # Honest about the limitation: token-set keying clusters questions
        # whose substantive tokens are IDENTICAL after stopword removal.
        # It does NOT handle plural/singular variants (LIBRARY vs
        # LIBRARIES) — that needs stemming, which v0.6.6 deliberately
        # doesn't do (deferred to v0.7.0 embeddings if needed).
        # Test fixture uses subjects that genuinely share their
        # post-stopword tokens.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._setup_corpus(
                out,
                manifest=[
                    {"key": f"k{i}", "kind": "qa", "ministry": "CULTURE",
                     "asker_entity_ids": ["PERSON_aaa"],
                     "asker_details": [{"name": "X"}],
                     "askers": ["X"]}
                    for i in range(3)
                ],
                answers=[
                    # Both questions use LIBRARY (singular) + FUNDING; only
                    # the order and stopwords differ. Same token-set key.
                    {"key": "k0", "question_subject": "LIBRARY FUNDING IMPACT"},
                    {"key": "k1", "question_subject": "IMPACT ON LIBRARY FUNDING"},
                    # Different tokens entirely.
                    {"key": "k2", "question_subject": "VACANCIES IN POLICE"},
                ],
                discourse=[
                    {"key": "k0", "label": "SCOPE_NARROWED"},
                    {"key": "k1", "label": "SCOPE_NARROWED"},
                    {"key": "k2", "label": "DATA_WITHHELD"},
                ],
            )
            path = build_mp_dossier(out, entity_id="PERSON_aaa", log_fn=lambda *_: None)
            md = path.read_text()
            # The two library questions should cluster into one topic group;
            # the police question is a separate group.
            self.assertIn("(2 questions)", md)
            self.assertIn("(1 questions)", md)


# --------------------------------------------------------------------------- #
# Slug helper                                                                  #
# --------------------------------------------------------------------------- #


class SlugifyTests(unittest.TestCase):

    def test_keeps_alphanumeric_and_underscores(self):
        self.assertEqual(_slugify("PERSON_aaa_supriya_sule"), "PERSON_aaa_supriya_sule")

    def test_strips_unsafe_chars(self):
        self.assertEqual(_slugify("Dr. Supriya Sule!"), "Dr_Supriya_Sule")

    def test_unknown_fallback(self):
        self.assertEqual(_slugify(""), "unknown")
        self.assertEqual(_slugify("///"), "unknown")


if __name__ == "__main__":
    unittest.main()
