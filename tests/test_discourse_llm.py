"""Tests for the LLM second-pass discourse classifier tier.

Coverage:
* ``classify_response_llm`` upgrades UNCLASSIFIED text to a recognised label
  when the mock endpoint returns a valid JSON label.
* FACTUAL_DISCLOSURE is accepted as a valid label (9th label, LLM-tier only).
* An unrecognised label returned by the LLM falls back to UNCLASSIFIED.
* A network failure falls back to UNCLASSIFIED (never raises).
* ``LLM_CLASSIFIER_VERSION`` is stamped on the output.
* ``analyse_discourse`` with ``llm_tier=True`` upgrades UNCLASSIFIED corpus
  records and increments ``stats.llm_classified``.
* Already-classified records are NOT sent to the LLM tier.
* ``stats.llm_unresolved`` counts calls where LLM still returned UNCLASSIFIED.
* ``DISCOURSE_LABEL_DESCRIPTIONS`` contains all nine labels.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from sansad_semantic_crawler.discourse import (
    CHANNEL_QA,
    CHANNEL_COMMITTEE,
    DISCOURSE_LABEL_DESCRIPTIONS,
    LLM_CLASSIFIER_VERSION,
    analyse_discourse,
    classify_response_llm,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_http_post(label: str, confidence: float = 0.85, reasoning: str = "test") -> Any:
    """Return a mock _http_post callable that always returns the given label."""
    def _post(endpoint: str, payload: dict, timeout_s: float) -> str:
        return json.dumps({"label": label, "confidence": confidence, "reasoning": reasoning})
    return _post


def _failing_http_post(endpoint: str, payload: dict, timeout_s: float) -> str:
    raise RuntimeError("connection refused")


def _write_answers(out: Path, rows: list[dict]) -> None:
    (out / "answers.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# classify_response_llm unit tests
# ---------------------------------------------------------------------------


class ClassifyResponseLlmTests(unittest.TestCase):

    def test_valid_label_returned_by_llm(self):
        c = classify_response_llm(
            "The Aspirational Districts Programme covers 112 districts.",
            CHANNEL_QA,
            _http_post=_make_http_post("FACTUAL_DISCLOSURE", 0.88, "plain factual answer"),
        )
        self.assertEqual(c.label, "FACTUAL_DISCLOSURE")
        self.assertAlmostEqual(c.confidence, 0.88)
        self.assertEqual(c.classifier, LLM_CLASSIFIER_VERSION)
        self.assertIn("factual", c.matched_pattern.lower())

    def test_factual_disclosure_is_accepted_label(self):
        self.assertIn("FACTUAL_DISCLOSURE", DISCOURSE_LABEL_DESCRIPTIONS)
        c = classify_response_llm(
            "District-level progress data: 112 aspirational districts.",
            CHANNEL_QA,
            _http_post=_make_http_post("FACTUAL_DISCLOSURE"),
        )
        self.assertEqual(c.label, "FACTUAL_DISCLOSURE")

    def test_all_eight_original_labels_accepted(self):
        for label in (
            "ACCEPTED", "DEFLECTED", "ABSORBED", "REJECTED",
            "SUBSTITUTED", "DATA_WITHHELD", "SCOPE_NARROWED", "CIRCULAR_REFERENCE",
        ):
            with self.subTest(label=label):
                c = classify_response_llm(
                    "sample text",
                    CHANNEL_QA,
                    _http_post=_make_http_post(label),
                )
                self.assertEqual(c.label, label)

    def test_unrecognised_label_falls_back_to_unclassified(self):
        c = classify_response_llm(
            "some text",
            CHANNEL_QA,
            _http_post=_make_http_post("TOTALLY_MADE_UP"),
        )
        self.assertEqual(c.label, "UNCLASSIFIED")
        self.assertEqual(c.confidence, 0.0)

    def test_network_failure_falls_back_to_unclassified(self):
        # Must not raise; callers expect a DiscourseClassification, not an exception.
        c = classify_response_llm(
            "some text",
            CHANNEL_QA,
            _http_post=_failing_http_post,
        )
        self.assertEqual(c.label, "UNCLASSIFIED")
        self.assertIn("LLM tier failed", c.political_function)

    def test_empty_text_returns_unclassified_without_calling_llm(self):
        called = []

        def _track_post(endpoint, payload, timeout_s):
            called.append(True)
            return "{}"

        c = classify_response_llm("", CHANNEL_QA, _http_post=_track_post)
        self.assertEqual(c.label, "UNCLASSIFIED")
        self.assertEqual(called, [], "LLM should not be called for empty text")

    def test_confidence_clamped_to_zero_one(self):
        c = classify_response_llm(
            "text",
            CHANNEL_QA,
            _http_post=_make_http_post("DEFLECTED", confidence=5.0),
        )
        self.assertLessEqual(c.confidence, 1.0)

        c2 = classify_response_llm(
            "text",
            CHANNEL_QA,
            _http_post=_make_http_post("DEFLECTED", confidence=-2.0),
        )
        self.assertGreaterEqual(c2.confidence, 0.0)

    def test_reasoning_truncated_to_120_chars(self):
        long_reason = "x" * 300
        c = classify_response_llm(
            "text",
            CHANNEL_QA,
            _http_post=_make_http_post("ACCEPTED", reasoning=long_reason),
        )
        self.assertLessEqual(len(c.matched_pattern), 120)

    def test_llm_classifier_version_stamped(self):
        c = classify_response_llm(
            "text",
            CHANNEL_QA,
            _http_post=_make_http_post("DEFLECTED"),
        )
        self.assertEqual(c.classifier, LLM_CLASSIFIER_VERSION)

    def test_channel_passed_in_user_message(self):
        """The payload sent to the LLM should include the channel hint."""
        captured: list[dict] = []

        def _capture_post(endpoint, payload, timeout_s):
            captured.append(payload)
            return json.dumps({"label": "DEFLECTED", "confidence": 0.8})

        classify_response_llm("text", CHANNEL_COMMITTEE, _http_post=_capture_post)
        user_msg = captured[0]["messages"][1]["content"]
        self.assertIn("committee", user_msg)


# ---------------------------------------------------------------------------
# Discourse label taxonomy completeness
# ---------------------------------------------------------------------------


class LabelTaxonomyTests(unittest.TestCase):
    def test_nine_labels_defined(self):
        self.assertEqual(len(DISCOURSE_LABEL_DESCRIPTIONS), 9)

    def test_all_original_eight_labels_present(self):
        for label in (
            "ACCEPTED", "DEFLECTED", "ABSORBED", "REJECTED",
            "SUBSTITUTED", "DATA_WITHHELD", "SCOPE_NARROWED", "CIRCULAR_REFERENCE",
        ):
            self.assertIn(label, DISCOURSE_LABEL_DESCRIPTIONS)

    def test_factual_disclosure_present(self):
        self.assertIn("FACTUAL_DISCLOSURE", DISCOURSE_LABEL_DESCRIPTIONS)

    def test_all_descriptions_are_non_empty_strings(self):
        for label, desc in DISCOURSE_LABEL_DESCRIPTIONS.items():
            self.assertIsInstance(desc, str)
            self.assertGreater(len(desc), 20, f"Description for {label} too short")


# ---------------------------------------------------------------------------
# analyse_discourse integration — LLM tier
# ---------------------------------------------------------------------------


class AnalyseDiscourseWithLlmTierTests(unittest.TestCase):

    def test_unclassified_records_upgraded_by_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            # Text that won't match any regex pattern → UNCLASSIFIED from Tier 1
            _write_answers(out, [{
                "key": "k1",
                "kind": "qa_response",
                "answer_text": (
                    "The Aspirational Districts Programme was launched in January 2018 "
                    "covering 112 districts across 28 States and Union Territories."
                ),
            }])
            stats = analyse_discourse(
                out,
                log_fn=lambda *_: None,
                llm_tier=True,
                _llm_http_post=_make_http_post("FACTUAL_DISCLOSURE", 0.90),
            )
            rec = json.loads((out / "analysis_discourse.jsonl").read_text().splitlines()[0])
        self.assertEqual(stats.llm_classified, 1)
        self.assertEqual(stats.llm_unresolved, 0)
        self.assertEqual(rec["label"], "FACTUAL_DISCLOSURE")
        self.assertEqual(rec["classifier"], LLM_CLASSIFIER_VERSION)

    def test_already_classified_records_not_sent_to_llm(self):
        """Regex-classified records must NOT be re-classified by the LLM tier."""
        llm_calls: list[bool] = []

        def _track_post(endpoint, payload, timeout_s):
            llm_calls.append(True)
            return json.dumps({"label": "DEFLECTED", "confidence": 0.9})

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_answers(out, [{
                "key": "k1",
                "kind": "qa_response",
                # This WILL match DATA_WITHHELD regex
                "answer_text": "No separate data is maintained at the central level.",
            }])
            analyse_discourse(
                out,
                log_fn=lambda *_: None,
                llm_tier=True,
                _llm_http_post=_track_post,
            )
        self.assertEqual(llm_calls, [], "LLM should not be called when regex classified")

    def test_llm_unresolved_incremented_when_llm_still_returns_unclassified(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_answers(out, [{
                "key": "k1",
                "kind": "qa_response",
                "answer_text": "Some completely opaque text with no recognisable pattern.",
            }])
            stats = analyse_discourse(
                out,
                log_fn=lambda *_: None,
                llm_tier=True,
                # LLM also can't classify it
                _llm_http_post=_make_http_post("UNCLASSIFIED_BY_LLM_TOO"),
            )
        self.assertEqual(stats.llm_classified, 0)
        self.assertEqual(stats.llm_unresolved, 1)

    def test_llm_tier_disabled_by_default(self):
        """Without llm_tier=True, no LLM call is made even for UNCLASSIFIED."""
        llm_calls: list[bool] = []

        def _track_post(endpoint, payload, timeout_s):
            llm_calls.append(True)
            return "{}"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_answers(out, [{
                "key": "k1",
                "kind": "qa_response",
                "answer_text": "Some opaque text that matches no regex pattern.",
            }])
            analyse_discourse(out, log_fn=lambda *_: None, _llm_http_post=_track_post)
        self.assertEqual(llm_calls, [])

    def test_llm_network_failure_leaves_record_as_unclassified(self):
        """A broken endpoint must not abort the corpus loop."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_answers(out, [{
                "key": "k1",
                "kind": "qa_response",
                "answer_text": "Opaque text with no regex match.",
            }])
            stats = analyse_discourse(
                out,
                log_fn=lambda *_: None,
                llm_tier=True,
                _llm_http_post=_failing_http_post,
            )
            rec = json.loads((out / "analysis_discourse.jsonl").read_text().splitlines()[0])
        self.assertEqual(stats.llm_unresolved, 1)
        self.assertEqual(rec["label"], "UNCLASSIFIED")
        self.assertEqual(stats.errors, [])  # error contained inside _maybe_llm_upgrade

    def test_llm_classifier_field_preserved_in_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_answers(out, [{
                "key": "k1",
                "kind": "qa_response",
                "answer_text": "The programme covers health, nutrition and education sectors.",
            }])
            analyse_discourse(
                out,
                log_fn=lambda *_: None,
                llm_tier=True,
                _llm_http_post=_make_http_post("FACTUAL_DISCLOSURE"),
            )
            rec = json.loads((out / "analysis_discourse.jsonl").read_text().splitlines()[0])
        self.assertEqual(rec["classifier"], LLM_CLASSIFIER_VERSION)

    def test_mixed_corpus_counts_correct(self):
        """Three records: one regex-hit, one LLM-upgraded, one LLM-unresolved."""
        def _selective_post(endpoint, payload, timeout_s):
            text = payload["messages"][1]["content"]
            if "factual" in text.lower():
                return json.dumps({"label": "FACTUAL_DISCLOSURE", "confidence": 0.85})
            return json.dumps({"label": "MYSTERY_LABEL", "confidence": 0.5})

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_answers(out, [
                # regex match → no LLM call
                {"key": "k1", "kind": "qa_response",
                 "answer_text": "Steps are being taken to expedite the process."},
                # LLM-upgradeable
                {"key": "k2", "kind": "qa_response",
                 "answer_text": "The factual details of the scheme are as follows."},
                # LLM returns unrecognised label
                {"key": "k3", "kind": "qa_response",
                 "answer_text": "Some text that is hard to categorise."},
            ])
            stats = analyse_discourse(
                out,
                log_fn=lambda *_: None,
                llm_tier=True,
                _llm_http_post=_selective_post,
            )
        self.assertEqual(stats.qa_classified, 3)
        self.assertEqual(stats.llm_classified, 1)
        self.assertEqual(stats.llm_unresolved, 1)


if __name__ == "__main__":
    unittest.main()
