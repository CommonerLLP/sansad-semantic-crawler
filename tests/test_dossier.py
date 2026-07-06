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

from commoner_analyse.dossier import (
    DOSSIER_VERSION,
    _name_matches,
    _normalize_topic_key,
    _slugify,
    build_ministry_dossier,
    build_mp_dossier,
    build_question_refinement,
    find_ministry_records,
    find_mp_records,
    parse_ministry_query,
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
        self.assertTrue(_name_matches("Sharma", "Aarav Sharma"))
        self.assertTrue(_name_matches("sharma", "AARAV SHARMA"))

    def test_substring_with_honorific(self):
        self.assertTrue(_name_matches("Aarav Sharma", "Smt. Aarav Sharma"))
        self.assertTrue(_name_matches("Iyer", "Dr V Iyer"))

    def test_no_match(self):
        self.assertFalse(_name_matches("Modi", "Aarav Sharma"))
        self.assertFalse(_name_matches("", "Aarav Sharma"))
        self.assertFalse(_name_matches("Sharma", ""))


# --------------------------------------------------------------------------- #
# Record selection                                                             #
# --------------------------------------------------------------------------- #


class FindMpRecordsTests(unittest.TestCase):

    def test_by_entity_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {"key": "k1", "kind": "qa", "ministry": "FINANCE",
                 "asker_entity_ids": ["PERSON_aaa_aarav_sharma"],
                 "asker_details": [{"name": "Aarav Sharma", "party": "NCP"}],
                 "askers": ["Aarav Sharma"]},
                {"key": "k2", "kind": "qa", "ministry": "AGRI",
                 "asker_entity_ids": ["PERSON_bbb_other"],
                 "asker_details": [{"name": "Other"}],
                 "askers": ["Other"]},
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [])
            pairs = find_mp_records(out, entity_id="PERSON_aaa_aarav_sharma")
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0][0]["key"], "k1")

    def test_by_name_loose_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {"key": "k1", "kind": "qa",
                 "asker_details": [{"name": "Smt. Aarav Sharma", "party": "NCP"}],
                 "askers": ["Smt. Aarav Sharma"]},
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [])
            pairs = find_mp_records(out, name="Sharma")
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


class FindMinistryRecordsTests(unittest.TestCase):

    def test_loose_ministry_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [
                {"key": "k1", "kind": "qa", "ministry": "HOME AFFAIRS",
                 "qtype": "Starred"},
                {"key": "k2", "kind": "qa", "ministry": "MINISTRY OF HOME AFFAIRS",
                 "qtype": "Unstarred"},
                {"key": "k3", "kind": "qa", "ministry": "SOCIAL JUSTICE AND EMPOWERMENT",
                 "qtype": "Unstarred"},
            ])
            _write_jsonl(out / "analysis_discourse.jsonl", [])
            _write_jsonl(out / "answers.jsonl", [])
            triples = find_ministry_records(out, ministry="Home Affairs")
            self.assertEqual(len(triples), 2)
            self.assertEqual({row[0]["key"] for row in triples}, {"k1", "k2"})

    def test_ministry_requires_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "manifest.jsonl", [])
            _write_jsonl(out / "analysis_discourse.jsonl", [])
            _write_jsonl(out / "answers.jsonl", [])
            with self.assertRaises(ValueError):
                find_ministry_records(out, ministry="")


class ParseMinistryQueryTests(unittest.TestCase):

    def test_starred_home_affairs_since_year(self):
        parsed = parse_ministry_query(
            "How many starred questions have been posed to the Ministry of Home Affairs since 2023?"
        )
        self.assertEqual(parsed.question_types, ("starred",))
        self.assertEqual(parsed.respondent_roles, ("cabinet", "mos"))
        self.assertEqual(parsed.ministries, ("HOME AFFAIRS",))
        self.assertEqual(parsed.houses, ("lok sabha", "rajya sabha"))
        self.assertEqual(parsed.people, ())
        self.assertEqual(parsed.date_from, "2023-01-01")
        self.assertIsNone(parsed.date_to)

    def test_amit_shah_home_and_cooperation_cabinet_only(self):
        parsed = parse_ministry_query(
            "Amit Shah, starred questions, Home Affairs and Cooperation, cabinet-only, since 2023"
        )
        self.assertEqual(parsed.question_types, ("starred",))
        self.assertEqual(parsed.respondent_roles, ("cabinet",))
        self.assertEqual(parsed.ministries, ("HOME AFFAIRS", "COOPERATION"))
        self.assertEqual(parsed.people, ("Amit Shah",))
        self.assertEqual(parsed.date_from, "2023-01-01")
        self.assertIsNone(parsed.date_to)

    def test_mos_home_date_range_and_rajya_sabha(self):
        parsed = parse_ministry_query(
            "unstarred questions answered by MoS Home between 2024-01-01 and 2024-12-31 in Rajya Sabha"
        )
        self.assertEqual(parsed.question_types, ("unstarred",))
        self.assertEqual(parsed.respondent_roles, ("mos",))
        self.assertEqual(parsed.ministries, ("HOME AFFAIRS",))
        self.assertEqual(parsed.houses, ("rajya sabha",))
        self.assertEqual(parsed.date_from, "2024-01-01")
        self.assertEqual(parsed.date_to, "2024-12-31")


class ParseMinistryQueryLlmTests(unittest.TestCase):

    def test_llm_fills_missing_house_and_role(self):
        def fake_http_post(*, endpoint, payload, timeout_s, api_key, allow_private):
            self.assertEqual(endpoint, "http://localhost:11434/v1")
            self.assertIn("messages", payload)
            return json.dumps({
                "respondent_roles": ["cabinet"],
                "houses": ["lok sabha"],
                "notes": ["fallback normalized implied house and role"],
            })

        parsed = parse_ministry_query(
            "Amit Shah, starred questions, Home Affairs and Cooperation, since 2023",
            llm_tier=True,
            _http_post=fake_http_post,
        )
        self.assertEqual(parsed.question_types, ("starred",))
        self.assertEqual(parsed.respondent_roles, ("cabinet",))
        self.assertEqual(parsed.ministries, ("HOME AFFAIRS", "COOPERATION"))
        self.assertEqual(parsed.houses, ("lok sabha",))
        self.assertEqual(parsed.people, ("Amit Shah",))
        self.assertEqual(parsed.date_from, "2023-01-01")
        self.assertIsNone(parsed.date_to)
        self.assertIn("llm fallback used", parsed.notes)


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
                        "asker_details": [{"name": "Dr V Iyer", "party": "CPI(M)", "state": "Kerala"}],
                        "askers": ["Dr V Iyer"],
                    },
                    {
                        "key": "k2", "kind": "qa", "ministry": "CULTURE",
                        "house": "Lok Sabha", "date": "2024-03-04",
                        "asker_entity_ids": ["PERSON_aaa"],
                        "asker_details": [{"name": "Dr V Iyer", "party": "CPI(M)", "state": "Kerala"}],
                        "askers": ["Dr V Iyer"],
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
            self.assertIn("Iyer", md)
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


class BuildMinistryDossierTests(unittest.TestCase):

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

    def test_ministry_dossier_renders_question_types_and_ministers(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._setup_corpus(
                out,
                manifest=[
                    {
                        "key": "k1", "kind": "qa", "ministry": "HOME AFFAIRS",
                        "house": "Lok Sabha", "date": "2024-01-10",
                        "qtype": "Starred", "title": "Border security",
                    },
                    {
                        "key": "k2", "kind": "qa", "ministry": "Home Affairs",
                        "house": "Lok Sabha", "date": "2024-02-11",
                        "qtype": "Unstarred", "title": "Police modernization",
                    },
                ],
                answers=[
                    {
                        "key": "k1", "kind": "qa_response",
                        "question_subject": "BORDER SECURITY",
                        "answer_minister_name": "SHRI AMIT SHAH",
                        "answer_body": "The Ministry has taken steps...",
                    },
                    {
                        "key": "k2", "kind": "qa_response",
                        "question_subject": "POLICE MODERNIZATION",
                        "answer_minister_name": "SHRI NITYANAND RAI",
                        "answer_body": "The Ministry has issued directions...",
                    },
                ],
                discourse=[
                    {"key": "k1", "label": "DEFLECTED", "channel": "qa",
                     "text_excerpt": "The Ministry has taken steps..."},
                    {"key": "k2", "label": "FACTUAL_DISCLOSURE", "channel": "qa",
                     "text_excerpt": "The Ministry has issued directions..."},
                ],
            )
            path = build_ministry_dossier(
                out,
                ministry="Home Affairs",
                log_fn=lambda *_: None,
            )
            self.assertIsNotNone(path)
            md = path.read_text()
            self.assertIn("Ministry Dossier", md)
            self.assertIn("HOME AFFAIRS", md)
            self.assertIn("**Question types:** Starred (1), Unstarred (1)", md)
            self.assertIn("SHRI AMIT SHAH", md)
            self.assertIn("SHRI NITYANAND RAI", md)
            self.assertIn("Border Security", md)
            self.assertIn("Police Modernization", md)
            self.assertIn(DOSSIER_VERSION, md)

    def test_no_match_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._setup_corpus(out, manifest=[])
            path = build_ministry_dossier(out, ministry="Home Affairs", log_fn=lambda *_: None)
            self.assertIsNone(path)
            self.assertFalse((out / "mp_dossiers").exists())


class BuildQuestionRefinementTests(unittest.TestCase):

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

    def test_refinement_writes_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._setup_corpus(
                out,
                manifest=[
                    {
                        "key": "k1", "kind": "qa", "ministry": "HOME AFFAIRS",
                        "house": "Lok Sabha", "date": "2024-01-10",
                        "qtype": "Starred", "title": "Border security",
                    },
                    {
                        "key": "k2", "kind": "qa", "ministry": "HOME AFFAIRS",
                        "house": "Lok Sabha", "date": "2024-02-11",
                        "qtype": "Starred", "title": "Police modernization",
                    },
                ],
                answers=[
                    {
                        "key": "k1", "kind": "qa_response",
                        "question_subject": "BORDER SECURITY",
                        "answer_minister_name": "SHRI AMIT SHAH",
                        "answer_text": "THE 10TH JANUARY, 2024 ... ANSWER THE MINISTER OF HOME AFFAIRS (SHRI AMIT SHAH) ...",
                        "answer_body": "The Ministry has approved steps...",
                    },
                    {
                        "key": "k2", "kind": "qa_response",
                        "question_subject": "POLICE MODERNIZATION",
                        "answer_minister_name": "SHRI NITYANAND RAI",
                        "answer_text": "THE 11TH FEBRUARY, 2024 ... ANSWER MINISTER OF STATE IN THE MINISTRY OF HOME AFFAIRS (SHRI NITYANAND RAI) ...",
                        "answer_body": "The Ministry has issued directions...",
                    },
                ],
                discourse=[
                    {"key": "k1", "label": "ACCEPTED", "channel": "qa",
                     "text_excerpt": "The Ministry has approved steps..."},
                    {"key": "k2", "label": "DATA_WITHHELD", "channel": "qa",
                     "text_excerpt": "The Ministry has issued directions..."},
                ],
            )
            path = build_question_refinement(
                out,
                query="Amit Shah, starred questions, Home Affairs, cabinet-only, since 2024",
                max_precedents=3,
                log_fn=lambda *_: None,
            )
            self.assertIsNotNone(path)
            md = path.read_text()
            data = json.loads((path.with_suffix(".json")).read_text())
            self.assertIn("Question Refinement", md)
            self.assertIn("Parsed Facets", md)
            self.assertIn("Cabinet Minister", md)
            self.assertIn("Amit Shah", md)
            self.assertEqual(data["parsed"]["question_types"], ["starred"])
            self.assertEqual(data["parsed"]["respondent_roles"], ["cabinet"])
            self.assertEqual(data["exact_match_count"], 1)
            self.assertGreaterEqual(len(data["precedents"]), 1)
            self.assertEqual(data["precedents"][0]["respondent_role"], "cabinet")
            self.assertEqual(data["precedents"][0]["answer_minister_name"], "SHRI AMIT SHAH")
            self.assertIn("accepted", data["risk_summary"].lower())

    def test_refinement_handles_no_exact_match_with_nearest_precedents(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._setup_corpus(
                out,
                manifest=[
                    {
                        "key": "k1", "kind": "qa", "ministry": "HOME AFFAIRS",
                        "house": "Lok Sabha", "date": "2024-01-10",
                        "qtype": "Starred", "title": "Border security",
                    },
                ],
                answers=[
                    {
                        "key": "k1", "kind": "qa_response",
                        "question_subject": "BORDER SECURITY",
                        "answer_minister_name": "SHRI NITYANAND RAI",
                        "answer_text": "THE 10TH JANUARY, 2024 ... ANSWER MINISTER OF STATE IN THE MINISTRY OF HOME AFFAIRS (SHRI NITYANAND RAI) ...",
                        "answer_body": "The Ministry has taken steps...",
                    },
                ],
                discourse=[
                    {"key": "k1", "label": "FACTUAL_DISCLOSURE", "channel": "qa",
                     "text_excerpt": "The Ministry has taken steps..."},
                ],
            )
            path = build_question_refinement(
                out,
                query="Amit Shah, starred questions, Home Affairs, cabinet-only, since 2024",
                max_precedents=3,
                log_fn=lambda *_: None,
            )
            data = json.loads((path.with_suffix(".json")).read_text())
            self.assertEqual(data["exact_match_count"], 0)
            self.assertGreaterEqual(len(data["precedents"]), 1)
            self.assertIn("No exact corpus match", data["refined_summary"])

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
                    "asker_entity_ids": ["PERSON_aaa_aarav_sharma"],
                    "asker_details": [{"name": "Aarav Sharma"}],
                    "askers": ["Aarav Sharma"],
                }],
                answers=[{"key": "k1", "kind": "qa_response", "question_subject": "PMFBY"}],
                discourse=[{"key": "k1", "label": "ACCEPTED"}],
            )
            path = build_mp_dossier(out, entity_id="PERSON_aaa_aarav_sharma", log_fn=lambda *_: None)
            self.assertEqual(path.name, "PERSON_aaa_aarav_sharma.md")

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
        self.assertEqual(_slugify("PERSON_aaa_aarav_sharma"), "PERSON_aaa_aarav_sharma")

    def test_strips_unsafe_chars(self):
        self.assertEqual(_slugify("Dr. Aarav Sharma!"), "Dr_Aarav_Sharma")

    def test_unknown_fallback(self):
        self.assertEqual(_slugify(""), "unknown")
        self.assertEqual(_slugify("///"), "unknown")


if __name__ == "__main__":
    unittest.main()
