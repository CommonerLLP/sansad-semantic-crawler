# Graph Smoke Workflow

Purpose: show how to build the SQLite read layer on a real checked-in corpus
without committing `graph.db`.

Input:

- `data/azad-demo/`

Commands:

```bash
cp -R data/azad-demo /private/tmp/ssc-graph-smoke
.venv/bin/python -m sansad_semantic_crawler build-graph \
  --out /private/tmp/ssc-graph-smoke
sqlite3 /private/tmp/ssc-graph-smoke/graph.db ".tables"
sqlite3 /private/tmp/ssc-graph-smoke/graph.db \
  "SELECT COUNT(*) FROM questions;"
sqlite3 /private/tmp/ssc-graph-smoke/graph.db \
  "SELECT kind, COUNT(*) FROM questions GROUP BY kind ORDER BY kind;"
sqlite3 /private/tmp/ssc-graph-smoke/graph.db \
  "SELECT record_key, question_subject FROM questions WHERE question_subject IS NOT NULL ORDER BY record_key LIMIT 3;"
```

Generated locally:

- `graph.db` (not committed)

Expected results from the current checked-in `data/azad-demo` corpus:

```text
.tables
_meta            classifications  memberships
atr_linkages     entities         questions

SELECT COUNT(*) FROM questions;
140

SELECT kind, COUNT(*) FROM questions GROUP BY kind ORDER BY kind;
qa_response|140

SELECT record_key, question_subject FROM questions WHERE question_subject IS NOT NULL ORDER BY record_key LIMIT 3;
LS|S|100|2024-12-02|‘Faculty Positions in CUs and HEIs’
LS|S|111|2025-12-08|Vacancies in Kendriya Vidyalaya Sangathan
LS|S|117|2025-07-28|
```

Why README-only:

The graph layer is useful as a runtime read surface, but `graph.db` is binary
and diff-hostile. This workflow therefore checks in commands and expected SQL
results rather than the database file itself.
