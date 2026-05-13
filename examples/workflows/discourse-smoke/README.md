# Discourse Smoke Workflow

Purpose: show `extract-answers` and `analyse-discourse`, including the additive
voice/agency fields on real QA responses.

Inputs:

- `data/azad-demo/`

Commands:

```bash
cp -R data/azad-demo /private/tmp/ssc-discourse-smoke
.venv/bin/python -m sansad_semantic_crawler extract-answers \
  --out /private/tmp/ssc-discourse-smoke
.venv/bin/python -m sansad_semantic_crawler analyse-discourse \
  --out /private/tmp/ssc-discourse-smoke
```

Inspect:

- `answers.jsonl` for extracted `question_text` / `answer_text` structure
- `analysis_discourse.jsonl` for discourse labels plus:
  - `voice`
  - `passive_ratio`
  - `agent_named`
  - `agent_terms`

Why frozen:

The checked-in rows below are copied from real corpus output and trimmed only to
remove volatile timestamps so the stable semantic-analysis fields are easy to
diff in review.
