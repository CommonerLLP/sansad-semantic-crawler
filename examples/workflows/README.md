# Workflow Examples

These folders are contributor-oriented worked examples.

- `basic-smoke/` shows the smallest `crawl` -> `parse` -> `export` path
  using the checked-in smoke corpus.
- `discourse-smoke/` shows `extract-answers` -> `analyse-discourse`,
  including the additive voice/agency fields.
- `graph-smoke/` shows `build-graph` against a real checked-in corpus and
  gives sample SQL with expected results in markdown.

Checked-in outputs here are intentionally tiny and text-based so output-shape
drift is reviewable in pull requests. Binary runtime artifacts such as
`graph.db` are not committed.
