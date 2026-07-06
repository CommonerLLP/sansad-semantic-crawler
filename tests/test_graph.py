"""Tests for the SQLite graph layer (graph.py)."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sansad_semantic_crawler.graph import (
    _compute_state_hash,
    _get_meta_value,
    _load_atr_linkages,
    _load_classifications,
    _load_entities,
    _load_questions,
    build_graph,
    init_db,
)


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class InitDbTests(unittest.TestCase):

    def test_creates_all_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(str(Path(tmp) / "g.db"))
            init_db(conn)
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            conn.close()
            self.assertIn("entities", tables)
            self.assertIn("questions", tables)
            self.assertIn("classifications", tables)
            self.assertIn("atr_linkages", tables)
            self.assertIn("memberships", tables)
            self.assertIn("_meta", tables)

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(str(Path(tmp) / "g.db"))
            init_db(conn)
            init_db(conn)  # second call must not raise
            conn.close()


class BuildGraphTests(unittest.TestCase):

    def test_empty_dir_returns_db_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            db = build_graph(out, log_fn=lambda _: None)
            self.assertTrue(db.exists())

    def test_default_db_path_is_graph_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            db = build_graph(out, log_fn=lambda _: None)
            self.assertEqual(db, out / "graph.db")

    def test_custom_db_path_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            custom = out / "subdir" / "custom.db"
            custom.parent.mkdir()
            db = build_graph(out, db_path=custom, log_fn=lambda _: None)
            self.assertEqual(db, custom)
            self.assertTrue(custom.exists())

    def test_idempotent_skips_rebuild_on_same_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            log: list[str] = []
            build_graph(out, log_fn=log.append)
            log.clear()
            build_graph(out, log_fn=log.append)
            self.assertTrue(any("up to date" in m for m in log))

    def test_rebuilds_when_content_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            build_graph(out, log_fn=lambda _: None)
            _write_jsonl(out / "answers.jsonl", [
                {"key": "RS|q|1", "session_no": 263, "house": "rs"},
            ])
            log: list[str] = []
            build_graph(out, log_fn=log.append)
            self.assertTrue(any("Building" in m for m in log))

    def test_content_hash_stored_in_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            db = build_graph(out, log_fn=lambda _: None)
            stored = _get_meta_value(db, "content_hash")
            expected = _compute_state_hash(out)
            self.assertEqual(stored, expected)


class LoadEntitiesTests(unittest.TestCase):

    def test_loads_people(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "entities" / "people.jsonl", [
                {"entity_id": "e1", "name": "Test MP", "party": "Test Party",
                 "state": "Test State", "house": "ls"},
            ])
            conn = sqlite3.connect(str(out / "g.db"))
            init_db(conn)
            count = _load_entities(conn, out)
            conn.commit()
            row = conn.execute("SELECT * FROM entities WHERE entity_id='e1'").fetchone()
            conn.close()
            self.assertEqual(count, 1)
            self.assertEqual(row[1], "Test MP")

    def test_missing_file_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(str(Path(tmp) / "g.db"))
            init_db(conn)
            count = _load_entities(conn, Path(tmp))
            conn.close()
            self.assertEqual(count, 0)


class LoadQuestionsTests(unittest.TestCase):

    def test_loads_record_with_scalar_asker(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "answers.jsonl", [
                {
                    "key": "RS|q|1",
                    "session_no": 263,
                    "house": "rs",
                    "kind": "unstarred",
                    "ministry": "EDUCATION",
                    "asker_entity_id": "e1",
                    "question_subject": "Library funding",
                    "answer_body": "No scheme exists.",
                },
            ])
            conn = sqlite3.connect(str(out / "g.db"))
            init_db(conn)
            count = _load_questions(conn, out)
            conn.commit()
            row = conn.execute(
                "SELECT asker_key, ministry FROM questions WHERE record_key='RS|q|1'"
            ).fetchone()
            conn.close()
            self.assertEqual(count, 1)
            self.assertEqual(row[0], "e1")
            self.assertEqual(row[1], "EDUCATION")

    def test_loads_record_with_list_asker(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "answers.jsonl", [
                {
                    "key": "RS|q|2",
                    "asker_entity_ids": ["e2", "e3"],
                    "question_subject": "Reservations",
                },
            ])
            conn = sqlite3.connect(str(out / "g.db"))
            init_db(conn)
            _load_questions(conn, out)
            conn.commit()
            row = conn.execute(
                "SELECT asker_key FROM questions WHERE record_key='RS|q|2'"
            ).fetchone()
            conn.close()
            self.assertEqual(row[0], "e2")


class LoadClassificationsTests(unittest.TestCase):

    def test_loads_classification_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "analysis_discourse.jsonl", [
                {
                    "record_key": "RS|q|1",
                    "label": "FEDERAL_DEFLECTION",
                    "classifier": "discourse_regex_v2",
                    "confidence": 1.0,
                    "audit_description": "State subject dodge",
                    "channel": "written",
                },
            ])
            conn = sqlite3.connect(str(out / "g.db"))
            init_db(conn)
            count = _load_classifications(conn, out)
            conn.commit()
            row = conn.execute(
                "SELECT label, classifier FROM classifications WHERE record_key='RS|q|1'"
            ).fetchone()
            conn.close()
            self.assertEqual(count, 1)
            self.assertEqual(row[0], "FEDERAL_DEFLECTION")


class LoadAtrLinkagesTests(unittest.TestCase):

    def test_loads_linkage_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(out / "atr_linkage.jsonl", [
                {
                    "key": "RS|education|374",
                    "references_report_no": "366",
                    "references_report_key": "RS|education|366",
                },
            ])
            conn = sqlite3.connect(str(out / "g.db"))
            init_db(conn)
            count = _load_atr_linkages(conn, out)
            conn.commit()
            row = conn.execute(
                "SELECT references_report_key FROM atr_linkages "
                "WHERE atr_record_key='RS|education|374'"
            ).fetchone()
            conn.close()
            self.assertEqual(count, 1)
            self.assertEqual(row[0], "RS|education|366")


if __name__ == "__main__":
    unittest.main()
