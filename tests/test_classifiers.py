import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sansad_semantic_crawler.classifiers import build_classifier
from sansad_semantic_crawler.classifiers.embeddings import EmbeddingsClassifier
from sansad_semantic_crawler.classifiers.ensemble import EnsembleClassifier
from sansad_semantic_crawler.classifiers.llm import LLMClassifier
from sansad_semantic_crawler.classifiers.regex import RegexClassifier, build_tag_rules
from sansad_semantic_crawler.topics import load_topic


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


if __name__ == "__main__":
    unittest.main()
