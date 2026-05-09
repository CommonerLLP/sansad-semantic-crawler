"""Tests for the Phase 4 weighting engine.

The weighting engine is the place where the corpus + entity table +
topic profile become a measurement. Tests pin:

* The substantive/evasive split (the eight discourse labels).
* Confidence-weighted aggregation.
* Bayesian shrinkage toward party prior.
* Provenance: every weight row carries `basis` with all knobs visible.
* The privacy guard: no annotation text leaks into output (β=0 today
  so this is a forward-compat check).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sansad_semantic_crawler.weighting import (
    DEFAULT_SHRINKAGE_N0,
    WEIGHTING_VERSION,
    _ActorCounts,
    _shrink,
    compute_weights,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _write_topic_profile(path: Path, name: str = "libraries") -> None:
    path.write_text(json.dumps({"name": name}), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Pure-helper tests                                                           #
# --------------------------------------------------------------------------- #


class ActorCountsTests(unittest.TestCase):
    def test_substantive_minus_evasive_over_total(self):
        c = _ActorCounts()
        c.add("ACCEPTED", 1.0, "run1")
        c.add("DEFLECTED", 1.0, "run1")
        # 1 substantive, 1 evasive → raw = 0
        self.assertEqual(c.raw_weight(), 0.0)

    def test_pure_substantive_yields_plus_one(self):
        c = _ActorCounts()
        c.add("ACCEPTED", 1.0, "r")
        c.add("REJECTED", 1.0, "r")  # both substantive
        self.assertEqual(c.raw_weight(), 1.0)

    def test_pure_evasive_yields_minus_one(self):
        c = _ActorCounts()
        c.add("DEFLECTED", 1.0, "r")
        c.add("ABSORBED", 1.0, "r")
        c.add("DATA_WITHHELD", 1.0, "r")
        self.assertEqual(c.raw_weight(), -1.0)

    def test_empty_returns_zero(self):
        self.assertEqual(_ActorCounts().raw_weight(), 0.0)
        self.assertEqual(_ActorCounts().effective_n(), 0.0)

    def test_confidence_weighting_lowers_evasive_contribution(self):
        # 1 ACCEPTED at conf 1.0; 2 DEFLECTED at conf 0.5 each.
        # substantive = 1.0; evasive = 1.0; raw = 0.
        c = _ActorCounts()
        c.add("ACCEPTED", 1.0, "r")
        c.add("DEFLECTED", 0.5, "r")
        c.add("DEFLECTED", 0.5, "r")
        self.assertEqual(c.raw_weight(), 0.0)

    def test_unclassified_label_still_aggregates_in_label_counts(self):
        c = _ActorCounts()
        c.add("ACCEPTED", 1.0, "r")
        # an "UNCLASSIFIED" wouldn't be passed in by the dispatcher, but
        # if it did, it shouldn't break the substantive/evasive split.
        c.add("UNCLASSIFIED", 1.0, "r")
        # raw_weight should consider only known labels.
        self.assertEqual(c.raw_weight(), 1.0)


class ShrinkageTests(unittest.TestCase):
    def test_shrinks_toward_prior_when_n_is_zero(self):
        # n=0 → posterior is fully the prior.
        self.assertEqual(_shrink(raw=1.0, prior=-0.5, effective_n=0.0, n0=10), -0.5)

    def test_no_shrinkage_when_n_is_huge(self):
        # n much larger than n0 → posterior ~= raw.
        post = _shrink(raw=1.0, prior=-0.5, effective_n=10000.0, n0=10)
        self.assertAlmostEqual(post, 1.0, places=2)

    def test_balanced_pull_at_n_equals_n0(self):
        # n == n0 → posterior is the average.
        post = _shrink(raw=1.0, prior=-1.0, effective_n=10.0, n0=10)
        self.assertEqual(post, 0.0)


# --------------------------------------------------------------------------- #
# Corpus integration tests                                                    #
# --------------------------------------------------------------------------- #


class ComputeWeightsTests(unittest.TestCase):
    def _setup_corpus(self, tmp: Path, *, party_for_eid: dict[str, str], discourse_rows: list[dict]):
        """Lay down minimal manifest + entities + analysis_discourse."""
        # Manifest: one record per discourse row, joining via key.
        manifest_rows = []
        for r in discourse_rows:
            manifest_rows.append({
                "key": r["key"],
                "asker_entity_ids": r.get("asker_entity_ids", []),
            })
        _write_jsonl(tmp / "manifest.jsonl", manifest_rows)

        # Entities: one mp_membership per (eid, party).
        ent_dir = tmp / "entities"
        ent_dir.mkdir(parents=True, exist_ok=True)
        memberships = []
        for eid, party in party_for_eid.items():
            memberships.append({
                "entity_id": eid, "party": party,
                "fetched_at": "2026-05-08T00:00:00",
                "house": "ls", "term": 18,
            })
        _write_jsonl(ent_dir / "mp_memberships.jsonl", memberships)

        # Analysis discourse.
        _write_jsonl(tmp / "analysis_discourse.jsonl", discourse_rows)

        # Topic profile.
        _write_topic_profile(tmp / "topic.json")

    def test_single_person_pure_evasion_party_pure_evasion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._setup_corpus(
                tmp,
                party_for_eid={"PERSON_a": "BJP"},
                discourse_rows=[
                    {"key": "k1", "asker_entity_ids": ["PERSON_a"],
                     "label": "DEFLECTED", "confidence": 1.0, "run_id": "r1"},
                    {"key": "k2", "asker_entity_ids": ["PERSON_a"],
                     "label": "DEFLECTED", "confidence": 1.0, "run_id": "r1"},
                ],
            )
            stats = compute_weights(tmp, topic_profile_path=tmp / "topic.json", log_fn=lambda *_: None)
            self.assertEqual(stats.person_rows, 1)
            self.assertEqual(stats.party_rows, 1)
            person_rows = [json.loads(l) for l in (tmp / "weights" / "person_topic.jsonl").read_text().splitlines()]
            party_rows = [json.loads(l) for l in (tmp / "weights" / "party_topic.jsonl").read_text().splitlines()]
        self.assertEqual(person_rows[0]["entity_id"], "PERSON_a")
        # Raw weight of pure evasion is -1; with shrinkage toward party prior
        # (which is also -1), posterior stays -1.
        self.assertEqual(person_rows[0]["weight"], -1.0)
        self.assertEqual(party_rows[0]["party"], "BJP")
        self.assertEqual(party_rows[0]["weight"], -1.0)

    def test_substantive_response_pulls_party_weight_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._setup_corpus(
                tmp,
                party_for_eid={"PERSON_a": "BJP", "PERSON_b": "BJP"},
                discourse_rows=[
                    # PERSON_a all evasion
                    {"key": "k1", "asker_entity_ids": ["PERSON_a"],
                     "label": "DEFLECTED", "confidence": 1.0, "run_id": "r1"},
                    {"key": "k2", "asker_entity_ids": ["PERSON_a"],
                     "label": "DEFLECTED", "confidence": 1.0, "run_id": "r1"},
                    # PERSON_b mixed: one substantive, one evasion → raw 0
                    {"key": "k3", "asker_entity_ids": ["PERSON_b"],
                     "label": "ACCEPTED", "confidence": 1.0, "run_id": "r1"},
                    {"key": "k4", "asker_entity_ids": ["PERSON_b"],
                     "label": "DEFLECTED", "confidence": 1.0, "run_id": "r1"},
                ],
            )
            compute_weights(tmp, topic_profile_path=tmp / "topic.json", log_fn=lambda *_: None)
            party_rows = [json.loads(l) for l in (tmp / "weights" / "party_topic.jsonl").read_text().splitlines()]
        # Party BJP: 1 ACCEPTED + 3 DEFLECTED → raw = (1-3)/4 = -0.5.
        self.assertEqual(party_rows[0]["weight"], -0.5)

    def test_shrinkage_pulls_small_n_person_toward_party_prior(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            # Party prior = 0 (mix of substantive and evasion across many).
            # Person with N=2 pure substantive should be pulled toward 0.
            rows = []
            # 20 mixed rows to establish party prior near 0.
            for i in range(10):
                rows.append({"key": f"prior_subst_{i}", "asker_entity_ids": ["PERSON_other"],
                             "label": "ACCEPTED", "confidence": 1.0, "run_id": "r1"})
                rows.append({"key": f"prior_evade_{i}", "asker_entity_ids": ["PERSON_other"],
                             "label": "DEFLECTED", "confidence": 1.0, "run_id": "r1"})
            # Target person with 2 pure substantive responses (raw = +1).
            rows.append({"key": "tgt1", "asker_entity_ids": ["PERSON_target"],
                         "label": "ACCEPTED", "confidence": 1.0, "run_id": "r1"})
            rows.append({"key": "tgt2", "asker_entity_ids": ["PERSON_target"],
                         "label": "ACCEPTED", "confidence": 1.0, "run_id": "r1"})
            self._setup_corpus(
                tmp,
                party_for_eid={"PERSON_other": "INC", "PERSON_target": "INC"},
                discourse_rows=rows,
            )
            compute_weights(tmp, topic_profile_path=tmp / "topic.json",
                            shrinkage_n0=10.0, log_fn=lambda *_: None)
            person_rows = {
                r["entity_id"]: r
                for r in (json.loads(l) for l in (tmp / "weights" / "person_topic.jsonl").read_text().splitlines())
            }
        target = person_rows["PERSON_target"]
        # The party prior is the AGGREGATE including the target person's
        # contributions (no leave-one-out in v0.5.0). With 10+2 ACCEPTED
        # and 10 DEFLECTED for INC: party_raw = (12-10)/22 ≈ 0.0909.
        # Target's posterior = (2 * 1.0 + 10 * 0.0909) / 12 ≈ 0.2424.
        self.assertAlmostEqual(target["basis"]["raw_weight"], 1.0, places=3)
        self.assertAlmostEqual(target["basis"]["prior_weight"], 0.0909, places=3)
        self.assertAlmostEqual(target["weight"], 0.2424, places=3)

    def test_basis_block_carries_full_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._setup_corpus(
                tmp,
                party_for_eid={"PERSON_a": "BJP"},
                discourse_rows=[
                    {"key": "k1", "asker_entity_ids": ["PERSON_a"],
                     "label": "ACCEPTED", "confidence": 0.9, "run_id": "run_xyz"},
                ],
            )
            compute_weights(tmp, topic_profile_path=tmp / "topic.json", log_fn=lambda *_: None)
            row = json.loads((tmp / "weights" / "person_topic.jsonl").read_text().splitlines()[0])
        basis = row["basis"]
        self.assertIn("raw_weight", basis)
        self.assertIn("prior_weight", basis)
        self.assertIn("posterior_weight", basis)
        self.assertIn("effective_n", basis)
        self.assertEqual(basis["shrinkage_n0"], DEFAULT_SHRINKAGE_N0)
        self.assertEqual(basis["method"], WEIGHTING_VERSION)
        self.assertTrue(basis["confidence_weighted"])
        self.assertEqual(basis["alpha_corpus"], 1.0)
        self.assertEqual(basis["beta_annotation"], 0.0)
        self.assertEqual(basis["from_run_ids"], ["run_xyz"])
        self.assertTrue(basis["topic_hash"].startswith("sha256:"))
        self.assertEqual(basis["corpus_kinds_included"], ["qa_response", "atr_response"])

    def test_unclassified_records_increment_stats_but_not_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._setup_corpus(
                tmp,
                party_for_eid={"PERSON_a": "BJP"},
                discourse_rows=[
                    {"key": "k1", "asker_entity_ids": ["PERSON_a"],
                     "label": "ACCEPTED", "confidence": 1.0, "run_id": "r"},
                    {"key": "k2", "asker_entity_ids": ["PERSON_a"],
                     "label": "UNCLASSIFIED", "confidence": 0.0, "run_id": "r"},
                    {"key": "k3", "asker_entity_ids": ["PERSON_a"],
                     "label": None, "confidence": None, "run_id": "r"},
                ],
            )
            stats = compute_weights(tmp, topic_profile_path=tmp / "topic.json", log_fn=lambda *_: None)
            self.assertEqual(stats.records_unclassifiable, 2)
            # Person row built from one valid label only.
            row = json.loads((tmp / "weights" / "person_topic.jsonl").read_text().splitlines()[0])
            self.assertEqual(row["engagement_count"], 1)

    def test_returns_empty_when_analysis_discourse_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _write_topic_profile(tmp / "topic.json")
            stats = compute_weights(tmp, topic_profile_path=tmp / "topic.json", log_fn=lambda *_: None)
        self.assertEqual(stats.person_rows, 0)
        self.assertEqual(stats.party_rows, 0)

    def test_weights_readme_written_on_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._setup_corpus(
                tmp,
                party_for_eid={"PERSON_a": "BJP"},
                discourse_rows=[
                    {"key": "k1", "asker_entity_ids": ["PERSON_a"],
                     "label": "ACCEPTED", "confidence": 1.0, "run_id": "r"},
                ],
            )
            compute_weights(tmp, topic_profile_path=tmp / "topic.json", log_fn=lambda *_: None)
            readme = (tmp / "weights" / "README.md").read_text()
        self.assertIn("substantive", readme.lower())
        self.assertIn("Bayesian", readme)
        self.assertIn("alpha", readme.lower())  # merge formula reference

    def test_no_long_text_fields_in_weights_outputs(self):
        """Privacy guard: even with β=0 today, a future regression that
        copies external-priors text into weights rows must fail this
        test. Public weights/*.jsonl must contain only numeric weights,
        IDs, and short metadata — never free-text fields.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._setup_corpus(
                tmp,
                party_for_eid={"PERSON_a": "BJP"},
                discourse_rows=[
                    {"key": "k1", "asker_entity_ids": ["PERSON_a"],
                     "label": "ACCEPTED", "confidence": 1.0, "run_id": "r"},
                ],
            )
            compute_weights(tmp, topic_profile_path=tmp / "topic.json", log_fn=lambda *_: None)
            for fname in ("person_topic.jsonl", "party_topic.jsonl"):
                content = (tmp / "weights" / fname).read_text()
                for line in content.splitlines():
                    rec = json.loads(line)
                    self._assert_no_long_strings(rec, path=f"{fname}")

    def _assert_no_long_strings(self, obj, *, path: str, max_len: int = 200):
        """Recursively walk JSON; fail if any string field is > max_len chars."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                self._assert_no_long_strings(v, path=f"{path}.{k}", max_len=max_len)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                self._assert_no_long_strings(v, path=f"{path}[{i}]", max_len=max_len)
        elif isinstance(obj, str):
            self.assertLessEqual(
                len(obj), max_len,
                f"long string field at {path} ({len(obj)} chars) — possible "
                f"annotation-text leak; weights/*.jsonl must contain only "
                f"numeric weights + IDs.",
            )


if __name__ == "__main__":
    unittest.main()
