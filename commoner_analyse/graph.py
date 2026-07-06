"""SQLite relationship layer over JSONL pipeline outputs.

Reads entities/, answers.jsonl, analysis_discourse.jsonl, manifest.jsonl,
atr_linkage.jsonl and loads them into a single indexed SQLite database.
Queries support the new scholar-friendly CLI commands without requiring
knowledge of JSONL structure or pipeline internals.

The JSONL pipeline is the primary data source; the graph is a derivative
read-layer. Rebuilding the graph from scratch is idempotent.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Callable

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    party TEXT,
    state TEXT,
    house TEXT
);

CREATE TABLE IF NOT EXISTS memberships (
    entity_id TEXT NOT NULL,
    role TEXT,
    context TEXT,
    from_date TEXT,
    to_date TEXT,
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
);

CREATE TABLE IF NOT EXISTS questions (
    record_key TEXT PRIMARY KEY,
    session_no INTEGER,
    qsl_no TEXT,
    session_date TEXT,
    house TEXT,
    kind TEXT,
    run_id TEXT,
    topic_hash TEXT,
    report_no TEXT,
    report_type TEXT,
    ministry TEXT,
    asker_key TEXT,
    responder_key TEXT,
    question_subject TEXT,
    question_body TEXT,
    answer_body TEXT
);

CREATE TABLE IF NOT EXISTS classifications (
    record_key TEXT NOT NULL,
    label TEXT,
    classifier TEXT,
    confidence REAL,
    audit_description TEXT,
    channel TEXT,
    FOREIGN KEY (record_key) REFERENCES questions(record_key)
);

CREATE TABLE IF NOT EXISTS atr_linkages (
    atr_record_key TEXT NOT NULL,
    references_report_no TEXT,
    references_report_key TEXT,
    FOREIGN KEY (atr_record_key) REFERENCES questions(record_key),
    FOREIGN KEY (references_report_key) REFERENCES questions(record_key)
);

CREATE TABLE IF NOT EXISTS _meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_questions_ministry ON questions(ministry);
CREATE INDEX IF NOT EXISTS idx_questions_asker ON questions(asker_key);
CREATE INDEX IF NOT EXISTS idx_questions_house ON questions(house);
CREATE INDEX IF NOT EXISTS idx_classifications_label ON classifications(label);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
"""


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't exist."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def build_graph(
    out_dir: Path,
    db_path: Path | None = None,
    log_fn: Callable[[str], None] = lambda msg: None,
) -> Path:
    """Ingest all pipeline outputs into a SQLite database.
    
    Reads from out_dir (answers.jsonl, manifest.jsonl, entities/, 
    analysis_discourse.jsonl, atr_linkage.jsonl) and writes to db_path.
    If db_path is None, defaults to out_dir / graph.db.
    
    Uses a content-hash to skip rebuild if nothing has changed.
    
    Returns the path to the created database.
    """
    if db_path is None:
        db_path = out_dir / "graph.db"
    
    current_hash = _compute_state_hash(out_dir)
    
    # Check if rebuild is needed
    if db_path.exists():
        stored_hash = _get_meta_value(db_path, "content_hash")
        if stored_hash == current_hash:
            log_fn("Graph up to date — skipping rebuild")
            return db_path
    
    log_fn("Building relationship graph...")
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    
    try:
        init_db(conn)
        
        _load_entities(conn, out_dir, log_fn)
        _load_questions(conn, out_dir, log_fn)
        _load_classifications(conn, out_dir, log_fn)
        _load_atr_linkages(conn, out_dir, log_fn)
        
        _set_meta_value(conn, "content_hash", current_hash)
        conn.commit()
        
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        
    log_fn(f"Graph built: {db_path}")
    return db_path


def _compute_state_hash(out_dir: Path) -> str:
    """Compute a hash of all relevant pipeline outputs."""
    files_to_hash = [
        out_dir / "answers.jsonl",
        out_dir / "analysis_discourse.jsonl",
        out_dir / "entities" / "people.jsonl",
        out_dir / "atr_linkage.jsonl",
    ]
    
    h = hashlib.sha256()
    for fpath in files_to_hash:
        if fpath.exists():
            h.update(fpath.read_bytes())
        else:
            h.update(b"")  # Non-existent files contribute empty bytes
            
    return h.hexdigest()


def _get_meta_value(db_path: Path, key: str) -> str | None:
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT value FROM _meta WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def _set_meta_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO _meta (key, value) VALUES (?, ?)",
        (key, value),
    )


def _load_entities(conn: sqlite3.Connection, out_dir: Path,
                   log_fn: Callable[[str], None] = lambda msg: None) -> int:
    """Load entities/people.jsonl into the entities table."""
    people_path = out_dir / "entities" / "people.jsonl"
    if not people_path.exists():
        log_fn("  No entities/people.jsonl found — skipping entities")
        return 0
    
    count = 0
    for line in people_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            person = json.loads(line)
            entity_id = person.get("entity_id")
            if not entity_id:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO entities (entity_id, name, party, state, house) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    entity_id,
                    person.get("name", ""),
                    person.get("party", ""),
                    person.get("state", ""),
                    person.get("house", ""),
                ),
            )
            count += 1
        except json.JSONDecodeError:
            continue
    
    conn.commit()
    log_fn(f"  Loaded {count} entities")
    return count


def _load_questions(conn: sqlite3.Connection, out_dir: Path,
                    log_fn: Callable[[str], None] = lambda msg: None) -> int:
    """Load answers.jsonl into the questions table."""
    answers_path = out_dir / "answers.jsonl"
    if not answers_path.exists():
        log_fn("  No answers.jsonl found — skipping questions")
        return 0
    
    count = 0
    for line in answers_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            key = rec.get("key")
            if not key:
                continue
            
            conn.execute(
                "INSERT OR REPLACE INTO questions "
                "(record_key, session_no, qsl_no, session_date, house, kind, "
                " run_id, topic_hash, report_no, report_type, ministry, "
                " asker_key, responder_key, question_subject, question_body, answer_body) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    rec.get("session_no"),
                    rec.get("qsl_no", ""),
                    rec.get("session_date", ""),
                    rec.get("house", ""),
                    rec.get("kind", ""),
                    rec.get("run_id", ""),
                    rec.get("topic_hash", ""),
                    rec.get("report_no", ""),
                    rec.get("report_type", ""),
                    rec.get("ministry", ""),
                    rec.get("asker_entity_id", rec.get("asker_entity_ids", [None])[0]
                            if isinstance(rec.get("asker_entity_ids"), list) and rec.get("asker_entity_ids")
                            else None),
                    rec.get("responder_entity_id", ""),
                    rec.get("question_subject", ""),
                    rec.get("question_body", ""),
                    rec.get("answer_body", rec.get("answer_text", "")),
                ),
            )
            count += 1
        except json.JSONDecodeError:
            continue
    
    conn.commit()
    log_fn(f"  Loaded {count} questions")
    return count


def _load_classifications(conn: sqlite3.Connection, out_dir: Path,
                          log_fn: Callable[[str], None] = lambda msg: None) -> int:
    """Load analysis_discourse.jsonl into the classifications table."""
    disc_path = out_dir / "analysis_discourse.jsonl"
    if not disc_path.exists():
        log_fn("  No analysis_discourse.jsonl found — skipping classifications")
        return 0
    
    count = 0
    for line in disc_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            record_key = rec.get("record_key")
            if not record_key:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO classifications "
                "(record_key, label, classifier, confidence, audit_description, channel) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record_key,
                    rec.get("label"),
                    rec.get("classifier", ""),
                    rec.get("confidence"),
                    rec.get("audit_description", ""),
                    rec.get("channel", ""),
                ),
            )
            count += 1
        except json.JSONDecodeError:
            continue
    
    conn.commit()
    log_fn(f"  Loaded {count} classifications")
    return count


def _load_atr_linkages(conn: sqlite3.Connection, out_dir: Path,
                       log_fn: Callable[[str], None] = lambda msg: None) -> int:
    """Load atr_linkage.jsonl into the atr_linkages table."""
    atr_path = out_dir / "atr_linkage.jsonl"
    if not atr_path.exists():
        log_fn("  No atr_linkage.jsonl found — skipping atr_linkages")
        return 0
    
    count = 0
    for line in atr_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            key = rec.get("key")
            if not key:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO atr_linkages "
                "(atr_record_key, references_report_no, references_report_key) "
                "VALUES (?, ?, ?)",
                (
                    key,
                    rec.get("references_report_no", ""),
                    rec.get("references_report_key", ""),
                ),
            )
            count += 1
        except json.JSONDecodeError:
            continue
    
    conn.commit()
    log_fn(f"  Loaded {count} atr_linkages")
    return count
