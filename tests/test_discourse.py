"""Tests for the Phase 2 surface discourse classifier.

Pin every label against canonical bureaucratic-register text so the
vocabulary is stable. The discourse labels are a contract for downstream
consumers (weighting engine, frontend); changing them later is a
breaking change.

Coverage:

* Each of the nine labels matched on a worked example.
* Channel-specific patterns correctly preferred over generic ones.
* UNCLASSIFIED returned (not raised) when no pattern matches.
* DFG records pass through with null discourse_label (no response yet).
* QA + ATR records flow into the corpus dispatcher correctly.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sansad_semantic_crawler.discourse import (
    CHANNEL_COMMITTEE,
    CHANNEL_QA,
    CLASSIFIER_VERSION,
    analyse_discourse,
    classify_response,
)


# ---------------------------------------------------------------------------
# Per-label classification
# ---------------------------------------------------------------------------


class ClassifyResponseLabelTests(unittest.TestCase):
    def test_accepted_on_concrete_commitment(self):
        text = (
            "The Government has approved the creation of 1,200 additional "
            "supernumerary posts vide notification dated 12.01.2024. "
            "An amount of Rs. 890 crore has been sanctioned w.e.f. 01.04.2024."
        )
        c = classify_response(text, CHANNEL_QA)
        self.assertEqual(c.label, "ACCEPTED")
        self.assertGreaterEqual(c.confidence, 0.8)
        self.assertTrue(c.matched_pattern)

    def test_rejected_on_explicit_disagreement(self):
        text = (
            "The Ministry does not agree with the observation of the Committee. "
            "The existing norms are adequate and any revision may not be "
            "feasible at this stage."
        )
        c = classify_response(text, CHANNEL_COMMITTEE)
        self.assertEqual(c.label, "REJECTED")

    def test_substituted_on_mission_mode_metric(self):
        text = (
            "A total of 12,543 appointments have been made under Mission Mode "
            "recruitment across all Central Universities during 2023-2025."
        )
        c = classify_response(text, CHANNEL_COMMITTEE)
        self.assertEqual(c.label, "CONSTITUTIONAL_DEFAULT")

    def test_deflected_on_under_consideration(self):
        text = (
            "The matter is under active consideration. Steps are being taken "
            "to expedite the process."
        )
        c = classify_response(text, CHANNEL_QA)
        self.assertEqual(c.label, "DEFLECTED")

    def test_absorbed_on_noted_for_compliance(self):
        text = (
            "The recommendation of the Committee has been noted for future "
            "compliance. The Ministry appreciates the concern expressed."
        )
        c = classify_response(text, CHANNEL_COMMITTEE)
        self.assertEqual(c.label, "ABSORBED")

    def test_factual_disclosure_on_long_form_answer(self):
        text = (
            "The States/UTs are primarily responsible for prevention, detection "
            "and investigation of cyber crime. The Central Government "
            "supplements the initiatives of the States/UTs through advisories "
            "and financial assistance. The number of cyber crime reporting "
            "units has been increased and the Ministry has set up a dedicated "
            "coordination mechanism."
        )
        c = classify_response(text, CHANNEL_QA)
        self.assertEqual(c.label, "FACTUAL_DISCLOSURE")

    def test_data_withheld_on_qa_response(self):
        text = (
            "No separate data on category-wise vacancy position is centrally "
            "maintained. The information is being collected from the "
            "respective universities and will be laid on the Table of the House."
        )
        c = classify_response(text, CHANNEL_QA)
        self.assertEqual(c.label, "DATA_WITHHELD")

    def test_scope_narrowed_jurisdiction_dodge(self):
        text = (
            "So far as this Ministry is concerned, the matter pertains to the "
            "respective State Governments and the University Grants Commission."
        )
        c = classify_response(text, CHANNEL_QA)
        self.assertEqual(c.label, "SCOPE_NARROWED")

    def test_circular_reference_in_committee_channel(self):
        text = (
            "The Ministry reiterates its earlier reply to Recommendation No. 2 "
            "of the 375th Report. As already stated, the matter is under active "
            "consideration."
        )
        c = classify_response(text, CHANNEL_COMMITTEE)
        self.assertEqual(c.label, "CIRCULAR_REFERENCE")


# ---------------------------------------------------------------------------
# Channel-aware priority
# ---------------------------------------------------------------------------


class ChannelPriorityTests(unittest.TestCase):
    def test_qa_prefers_data_withheld_over_deflected(self):
        # Text contains BOTH a DATA_WITHHELD pattern and a DEFLECTED pattern.
        # Channel-specific (DATA_WITHHELD) must win when channel is qa.
        text = (
            "No separate data is maintained. The matter is being examined."
        )
        c = classify_response(text, CHANNEL_QA)
        self.assertEqual(c.label, "DATA_WITHHELD")

    def test_committee_prefers_circular_reference_over_deflected(self):
        text = (
            "As already stated, the matter is under active consideration. "
            "Steps are being taken."
        )
        c = classify_response(text, CHANNEL_COMMITTEE)
        self.assertEqual(c.label, "CIRCULAR_REFERENCE")

    def test_qa_does_not_match_committee_only_circular_reference(self):
        # CIRCULAR_REFERENCE is committee-only. In QA channel, this text
        # should fall through to other patterns; the "as already stated"
        # phrase isn't in QA's priority list.
        text = (
            "As stated in the reply to Recommendation No. 5, the matter "
            "is under active consideration."
        )
        c = classify_response(text, CHANNEL_QA)
        # Should match DEFLECTED (under active consideration) since
        # CIRCULAR_REFERENCE isn't in QA priority.
        self.assertEqual(c.label, "DEFLECTED")


class UnclassifiedTests(unittest.TestCase):
    def test_no_pattern_match_returns_unclassified(self):
        text = "This is a perfectly normal English sentence about gardening."
        c = classify_response(text, CHANNEL_QA)
        self.assertEqual(c.label, "UNCLASSIFIED")
        self.assertEqual(c.confidence, 0.0)

    def test_empty_text_returns_unclassified(self):
        self.assertEqual(classify_response("", CHANNEL_QA).label, "UNCLASSIFIED")
        self.assertEqual(classify_response(None, CHANNEL_QA).label, "UNCLASSIFIED")


# ---------------------------------------------------------------------------
# Corpus dispatcher
# ---------------------------------------------------------------------------


def _write_answers(out: Path, rows: list[dict]) -> None:
    (out / "answers.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )


class AnalyseDiscourseTests(unittest.TestCase):
    def test_qa_responses_get_qa_channel_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_answers(out, [{
                "key": "LS|U|178|2026-03-17",
                "kind": "qa_response",
                "answer_text": "No separate data is maintained at the central level.",
                "extractor": "regex_v1",
            }])
            stats = analyse_discourse(out, log_fn=lambda *_: None)
            self.assertEqual(stats.qa_classified, 1)
            rows = (out / "analysis_discourse.jsonl").read_text().splitlines()
            rec = json.loads(rows[0])
        self.assertEqual(rec["label"], "DATA_WITHHELD")
        self.assertEqual(rec["channel"], "qa")
        self.assertEqual(rec["kind"], "qa_response_analysis")
        self.assertEqual(rec["classifier"], CLASSIFIER_VERSION)

    def test_atr_responses_get_committee_channel_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_answers(out, [{
                "key": "RS|education|378",
                "kind": "atr_response",
                "recommendation_no": 1,
                "response_text": "The recommendation has been noted for future compliance.",
                "extractor": "regex_v1",
            }])
            stats = analyse_discourse(out, log_fn=lambda *_: None)
            self.assertEqual(stats.atr_classified, 1)
            rec = json.loads((out / "analysis_discourse.jsonl").read_text().splitlines()[0])
        self.assertEqual(rec["label"], "ABSORBED")
        self.assertEqual(rec["channel"], "committee")
        self.assertEqual(rec["recommendation_no"], 1)
        self.assertEqual(rec["kind"], "atr_response_analysis")

    def test_dfg_recommendations_pass_through_with_null_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_answers(out, [{
                "key": "RS|education|377",
                "kind": "dfg_recommendation",
                "recommendation_no": 1,
                "recommendation_text": "The Committee recommends that...",
                "extractor": "regex_v1",
            }])
            stats = analyse_discourse(out, log_fn=lambda *_: None)
            self.assertEqual(stats.dfg_passed_through, 1)
            self.assertEqual(stats.atr_classified, 0)
            self.assertEqual(stats.qa_classified, 0)
            rec = json.loads((out / "analysis_discourse.jsonl").read_text().splitlines()[0])
        self.assertIsNone(rec["label"])
        self.assertEqual(rec["channel"], "dfg")
        self.assertEqual(rec["kind"], "dfg_recommendation_passthrough")

    def test_label_counts_aggregated_in_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_answers(out, [
                {"key": "k1", "kind": "qa_response",
                 "answer_text": "Steps are being taken.", "extractor": "regex_v1"},
                {"key": "k2", "kind": "qa_response",
                 "answer_text": "The Government does not agree.", "extractor": "regex_v1"},
                {"key": "k3", "kind": "qa_response",
                 "answer_text": "Steps are being taken in due course.", "extractor": "regex_v1"},
            ])
            stats = analyse_discourse(out, log_fn=lambda *_: None)
        self.assertEqual(stats.label_counts.get("DEFLECTED"), 2)
        self.assertEqual(stats.label_counts.get("REJECTED"), 1)

    def test_skips_records_with_empty_response_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_answers(out, [{
                "key": "RS|finance|99",
                "kind": "atr_response",
                "recommendation_no": 1,
                "response_text": "",  # empty
                "extractor": "regex_v1",
            }])
            stats = analyse_discourse(out, log_fn=lambda *_: None)
            self.assertEqual(stats.skipped_empty_response, 1)
            self.assertEqual(stats.atr_classified, 0)

    def test_returns_empty_stats_when_answers_jsonl_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            stats = analyse_discourse(out, log_fn=lambda *_: None)
            self.assertEqual(stats.qa_classified, 0)
            self.assertEqual(stats.atr_classified, 0)
            self.assertFalse((out / "analysis_discourse.jsonl").exists())


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()


class NewRegexV2PatternsTest(unittest.TestCase):
    """Tests for new regex_v2 patterns mined from Azad corpus UNCLASSIFIED records."""

    def test_instruments_issued_fires_absorbed(self):
        from sansad_semantic_crawler.discourse import CHANNEL_QA
        result = classify_response(
            "As per the instructions issued by DoPT, each Ministry/Department "
            "is required to appoint an officer not below the rank of Deputy Secretary "
            "as Liaison Officer for SC/ST and OBC.",
            channel=CHANNEL_QA,
        )
        self.assertEqual(result.label, "ABSORBED")

    def test_government_enacted_fires_absorbed(self):
        from sansad_semantic_crawler.discourse import CHANNEL_QA
        result = classify_response(
            "The Government enacted Rights of Persons with Disabilities (RPwD) Act, "
            "2016 which came into force on 19.04.2017.",
            channel=CHANNEL_QA,
        )
        self.assertEqual(result.label, "ABSORBED")

    def test_section_of_act_fires_absorbed(self):
        from sansad_semantic_crawler.discourse import CHANNEL_QA
        result = classify_response(
            "Section 34 of the RPWD Act 2016 provides for 4 percent reservation "
            "in the government employment to persons with benchmark disabilities.",
            channel=CHANNEL_QA,
        )
        self.assertEqual(result.label, "ABSORBED")

    def test_continuous_process_fires_absorbed(self):
        from sansad_semantic_crawler.discourse import CHANNEL_QA
        result = classify_response(
            "Occurrence and filling of vacancies is a continuous process. "
            "Instructions have been issued to all Ministries/Departments.",
            channel=CHANNEL_QA,
        )
        self.assertEqual(result.label, "ABSORBED")

    def test_state_subject_fires_federal_deflection(self):
        from sansad_semantic_crawler.discourse import CHANNEL_QA
        result = classify_response(
            "Whereas Land is a state subject, several states have state specific "
            "Land Revenue Codes and rules which provide for the protection of "
            "land rights of marginalized communities.",
            channel=CHANNEL_QA,
        )
        self.assertEqual(result.label, "FEDERAL_DEFLECTION")

    def test_concurrent_list_fires_federal_deflection(self):
        from sansad_semantic_crawler.discourse import CHANNEL_QA
        result = classify_response(
            "Education is a subject in the Concurrent List of the Constitution. "
            "Schools, other than those owned by the Central Government, are under "
            "the jurisdiction of the respective State Governments.",
            channel=CHANNEL_QA,
        )
        self.assertEqual(result.label, "FEDERAL_DEFLECTION")

    def test_governing_body_fires_representational_silence(self):
        from sansad_semantic_crawler.discourse import CHANNEL_QA
        result = classify_response(
            "There are 16 Deans working in the University who are appointed from "
            "among the faculties. Members of the governing body are as follows.",
            channel=CHANNEL_QA,
        )
        self.assertEqual(result.label, "REPRESENTATIONAL_SILENCE")

    def test_annexure_reference_fires_substituted(self):
        from sansad_semantic_crawler.discourse import CHANNEL_QA
        result = classify_response(
            "The details of Departments of 63 Lateral Entry officers and their "
            "positions are enclosed at Annexure-I.",
            channel=CHANNEL_QA,
        )
        self.assertEqual(result.label, "SUBSTITUTED")

    def test_autonomous_institution_fires_scope_narrowed(self):
        from sansad_semantic_crawler.discourse import CHANNEL_QA
        result = classify_response(
            "Indian Institutes of Technology (IITs) are autonomous Institutions "
            "governed by Institute of Technology Act, 1961 and the statutes framed "
            "thereunder.",
            channel=CHANNEL_QA,
        )
        self.assertEqual(result.label, "SCOPE_NARROWED")

    def test_scheme_launch_fires_absorbed(self):
        from sansad_semantic_crawler.discourse import CHANNEL_QA
        result = classify_response(
            "The Nai Roshni Scheme, a Leadership Development Programme for "
            "Minority Women was launched in 2012-13 with an objective to empower "
            "and instill confidence among minority women.",
            channel=CHANNEL_QA,
        )
        self.assertEqual(result.label, "ABSORBED")

    def test_niti_aayog_reference_fires_absorbed(self):
        from sansad_semantic_crawler.discourse import CHANNEL_QA
        result = classify_response(
            "NITI Aayog, in its three year Action Agenda, and the Sectoral Group "
            "of Secretaries recommended for induction of personnel in the middle "
            "and senior management level.",
            channel=CHANNEL_QA,
        )
        self.assertEqual(result.label, "ABSORBED")

    def test_central_sector_scheme_fires_absorbed(self):
        from sansad_semantic_crawler.discourse import CHANNEL_QA
        result = classify_response(
            "The Pradhan Mantri Virasat Ka Samvardhan (PM VIKAS) is a Central "
            "Sector Scheme focusing on the socio-economic empowerment of six "
            "notified minorities through skill development.",
            channel=CHANNEL_QA,
        )
        self.assertEqual(result.label, "ABSORBED")
