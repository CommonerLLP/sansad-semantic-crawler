# Basic Smoke Workflow

Purpose: show the smallest `crawl` -> `parse` -> `export` path using the
checked-in library smoke corpus.

Inputs:

- `examples/topics/libraries.json`
- `examples/corpora/smoke/manifest.jsonl`

Commands:

```bash
cp -R examples/corpora/smoke /private/tmp/ssc-basic-smoke
.venv/bin/python -m sansad_semantic_crawler parse \
  --topic examples/topics/libraries.json \
  --out /private/tmp/ssc-basic-smoke \
  --refresh-text
.venv/bin/python -m sansad_semantic_crawler export \
  --topic examples/topics/libraries.json \
  --out /private/tmp/ssc-basic-smoke
```

Inspect:

- `manifest.jsonl` for the tiny corpus records
- `analysis.jsonl` for topic-classification output shape

Why frozen:

The checked-in outputs below are a byte-stable representative slice of what the
current parser emits for the smoke corpus. Volatile timing fields are omitted so
review stays focused on interface shape rather than run-to-run noise.
