import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from commoner_analyse.classifiers import build_classifier
from commoner_analyse.classifiers.embeddings import EmbeddingsClassifier
from commoner_analyse.classifiers.ensemble import EnsembleClassifier
from commoner_analyse.classifiers.llm import LLMClassifier
from commoner_analyse.classifiers.regex import RegexClassifier, build_tag_rules
from commoner_analyse.topics import load_topic


class ClassifierTests(unittest.TestCase):
    def test_embeddings_classifier_uses_anchor_similarity_without_model_download(self):
        vectors = {
            "public library": [1.0, 0.0],
            "digital library": [0.0, 1.0],
            "district public library grant": [0.9, 0.1],
        }

        def encode(texts):
            return [vectors[text] for text in texts]

        classifier = EmbeddingsClassifier(
            embedding_model="fake-model",
            anchors={
                "public_library": ["public library"],
                "digital_library": ["digital library"],
            },
            threshold=0.8,
            encoder=encode,
        )
        result = classifier.classify("district public library grant")
        self.assertIn("public_library", result.tags)
        self.assertNotIn("digital_library", result.tags)
        self.assertEqual(result.model, "fake-model")

    def test_llm_classifier_parses_chat_completions_json_response(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"tags":["public_library"],"confidence":{"public_library":0.91},"reasoning":"mentions libraries"}'
                    )
                )
            ]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: response)
            )
        )
        classifier = LLMClassifier(
            endpoint="http://localhost:11434/v1",
            model="fake-llm",
            tag_definitions={"public_library": "Public library questions"},
            client=client,
        )
        result = classifier.classify("Question about public libraries")
        self.assertEqual(result.tags, ["public_library"])
        self.assertAlmostEqual(result.matches["public_library"], 0.91)
        self.assertEqual(result.model, "fake-llm")

    def test_llm_classifier_falls_back_to_tags_in_non_json_response(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="The best tag is public_library.")
                )
            ]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: response)
            )
        )
        classifier = LLMClassifier(
            endpoint="http://localhost:11434/v1",
            model="fake-llm",
            tag_definitions={"public_library": "Public library questions"},
            client=client,
        )
        result = classifier.classify("Question about public libraries")
        self.assertEqual(result.tags, ["public_library"])
        self.assertIn("non-JSON", result.explain)

    def test_ensemble_supports_union_intersection_and_weighted(self):
        rules_a = build_tag_rules([{"tag": "a", "patterns": ["alpha"]}])
        rules_b = build_tag_rules([{"tag": "b", "patterns": ["beta"]}])
        a = RegexClassifier(rules_a)
        b = RegexClassifier(rules_b)

        union = EnsembleClassifier([a, b], combine="union").classify("alpha beta")
        self.assertEqual(union.tags, ["a", "b"])

        intersection = EnsembleClassifier([a, b], combine="intersection").classify("alpha beta")
        self.assertEqual(intersection.tags, [])

        weighted = EnsembleClassifier([a, b], combine="weighted", weights={"regex": 2.0}).classify("alpha beta")
        self.assertEqual(weighted.tags, ["a", "b"])
        self.assertEqual(weighted.matches["a"], 2.0)

    def test_profile_classifier_block_selects_embeddings_mode(self):
        profile = """
        {
          "name": "demo",
          "search_groups": {"x": ["library"]},
          "classifier": {
            "mode": "embeddings",
            "embedding_model": "fake-model",
            "anchors": {"public_library": ["public library"]},
            "threshold": 0.5
          }
        }
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topic.json"
            path.write_text(profile, encoding="utf-8")
            topic = load_topic(path)
        self.assertEqual(topic.classifier.name, "embeddings")

    def test_classifier_override_preserves_regex_back_compat(self):
        profile = """
        {
          "name": "demo",
          "tag_rules": [{"tag": "public_library", "patterns": ["public\\\\s+librar"]}]
        }
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topic.json"
            path.write_text(profile, encoding="utf-8")
            topic = load_topic(path, classifier_override="regex")
        result = topic.classify("public libraries")
        self.assertIn("public_library", result["tags"])
        self.assertEqual(result["classifier"], "regex")

    def test_build_classifier_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            build_classifier({"mode": "mystery"}, tag_rules=(), fallback_tag="topic_match")


class RegexExcludePatternsTests(unittest.TestCase):
    """Tests for `exclude_patterns` disambiguation in TagRule.

    Surfaced 2026-05-08: a profile rule like ``\\bDRI\\b`` catches both
    "Directorate of Revenue Intelligence" (the customs/smuggling agency)
    and unrelated occurrences like "DRI scheme" (a banking initiative).
    The exclude_patterns layer lets the rule author suppress the false
    positive by naming the disambiguator.
    """

    def test_match_without_exclude_patterns_behaves_as_v0_4_0(self):
        """Backwards compat: rules without exclude_patterns count exactly as before."""
        rules = build_tag_rules([{"tag": "dri", "patterns": [r"\bDRI\b"]}])
        clf = RegexClassifier(rules)
        result = clf.classify("The DRI seized 100 kg of contraband.")
        self.assertEqual(result.tags, ["dri"])
        self.assertEqual(result.matches["dri"], 1.0)

    def test_exclude_pattern_suppresses_match_in_window(self):
        """The DRI-scheme false positive is exactly the case that motivated this."""
        rules = build_tag_rules([{
            "tag": "dri",
            "patterns": [r"\bDRI\b"],
            "exclude_patterns": [r"DRI\s+scheme"],
        }])
        clf = RegexClassifier(rules)
        result = clf.classify("The DRI scheme was launched in 2018 by the Finance Ministry.")
        self.assertNotIn("dri", result.tags)
        self.assertEqual(result.matches.get("dri", 0), 0)

    def test_only_the_dri_inside_dri_scheme_is_suppressed(self):
        """Per-occurrence: only the include match contained in an exclude span
        is suppressed. Other ``\\bDRI\\b`` matches elsewhere in the same
        document still count.
        """
        text = (
            "The DRI seized 100 kg of contraband. The DRI later confirmed "
            "the seizure was part of an ongoing operation. (Unrelated: "
            "the DRI scheme of the Reserve Bank of India was amended.)"
        )
        rules = build_tag_rules([{
            "tag": "dri",
            "patterns": [r"\bDRI\b"],
            "exclude_patterns": [r"DRI\s+scheme"],
        }])
        clf = RegexClassifier(rules)
        result = clf.classify(text)
        self.assertIn("dri", result.tags)
        # Two customs DRI mentions count; the third ("DRI scheme") is
        # suppressed by containment in the exclude span.
        self.assertEqual(result.matches["dri"], 2.0)

    def test_partial_suppression_when_some_matches_are_near_excludes(self):
        """Per-match suppression: each include match independently checked."""
        rules = build_tag_rules([{
            "tag": "dri",
            "patterns": [r"\bDRI\b"],
            "exclude_patterns": [r"DRI\s+scheme"],
        }])
        clf = RegexClassifier(rules)
        # Two "DRI" mentions: one is in "DRI scheme" (suppressed),
        # the other stands alone (counted).
        result = clf.classify("DRI raids continued. Meanwhile the DRI scheme failed.")
        self.assertEqual(result.matches["dri"], 1.0)

    def test_exclude_patterns_compile_with_case_insensitive_flag(self):
        """Exclude patterns honor IGNORECASE / DOTALL like include patterns."""
        rules = build_tag_rules([{
            "tag": "dri",
            "patterns": [r"\bDRI\b"],
            "exclude_patterns": [r"dri\s+SCHEME"],  # mixed case
        }])
        clf = RegexClassifier(rules)
        result = clf.classify("The DRI Scheme was announced.")
        self.assertNotIn("dri", result.tags)

    def test_weight_applied_only_to_non_excluded_matches(self):
        """Score = (non-excluded matches) × weight."""
        rules = build_tag_rules([{
            "tag": "dri",
            "patterns": [r"\bDRI\b"],
            "exclude_patterns": [r"DRI\s+scheme"],
            "weight": 2.5,
        }])
        clf = RegexClassifier(rules)
        result = clf.classify("DRI raids continued. The DRI scheme failed.")
        # 1 non-excluded match × 2.5 weight = 2.5 score.
        self.assertEqual(result.score, 2.5)

    def test_multiple_include_and_exclude_patterns_per_rule(self):
        """All include patterns + all exclude patterns interact correctly."""
        rules = build_tag_rules([{
            "tag": "narcotics_enforcement",
            "patterns": [
                r"\bDRI\b",
                r"\bNCB\b",
                r"Narcotics\s+Control\s+Bureau",
            ],
            "exclude_patterns": [
                r"DRI\s+scheme",
                r"NCB-(?:rated|league)",  # not the bureau, the basketball thing
            ],
        }])
        clf = RegexClassifier(rules)
        result = clf.classify(
            "DRI and NCB jointly busted a heroin ring. The Narcotics "
            "Control Bureau confirmed seizures. (Unrelated: DRI scheme of RBI.)"
        )
        # 3 valid matches: DRI (busted), NCB (jointly), Narcotics Control Bureau.
        # 1 suppressed: DRI in "DRI scheme of RBI".
        self.assertEqual(result.matches["narcotics_enforcement"], 3.0)


if __name__ == "__main__":
    unittest.main()
