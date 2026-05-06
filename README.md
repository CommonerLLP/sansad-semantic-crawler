# Sansad Semantic Crawler

A self-contained crawler for Indian Parliament questions across arbitrary
topics. It knows the Lok Sabha DSpace API and the Rajya Sabha question API,
but the topic logic lives in JSON profiles, so other projects can add or
extend subjects without editing crawler code.

## What It Does

- Crawls Lok Sabha questions from `elibrary.sansad.in`.
- Crawls Rajya Sabha questions from `rsdoc.nic.in`.
- Normalizes both houses into one JSONL manifest.
- Downloads answer PDFs when requested.
- Extracts text from PDFs with `pdftotext -layout`, falling back to
  `pdfminer.six` when installed.
- Tags records with topic-defined semantic regex rules.
- Exports reusable summary JSON or browser-ready JS.

## Quick Start

```bash
cd sansad-semantic-crawler

# Dry smoke crawl: one search bucket, five records, no PDFs.
python -m sansad_semantic_crawler crawl \
  --topic examples/topics/libraries.json \
  --out data/libraries \
  --max-buckets 1 \
  --max-records 5 \
  --no-download

# Download a tiny sample.
python -m sansad_semantic_crawler crawl \
  --topic examples/topics/libraries.json \
  --out data/libraries \
  --house ls \
  --max-buckets 1 \
  --max-records 1

# Parse PDFs/text and export both analysis + summary JSON.
python -m sansad_semantic_crawler parse --topic examples/topics/libraries.json --out data/libraries
python -m sansad_semantic_crawler export --topic examples/topics/libraries.json --out data/libraries --format json

# Browser-ready JS export for static sites.
python -m sansad_semantic_crawler export \
  --topic examples/topics/libraries.json \
  --out data/libraries \
  --format js \
  --js-global PARLIAMENT_LIBRARY_DATA \
  --export-path data/libraries/parliament_libraries.js
```

## Topic Profiles

Profiles are JSON files. A minimal profile:

```json
{
  "name": "libraries",
  "description": "Public and institutional library questions",
  "search_groups": {
    "public_library": ["public library", "district library"],
    "digital": ["digital library", "National Digital Library"]
  },
  "lok_sabha_ministries": ["CULTURE", "EDUCATION"],
  "rajya_sabha_ministry_likes": ["CULTURE", "EDUCATION"],
  "tag_rules": [
    {"tag": "public_library", "label": "Public libraries", "patterns": ["public\\\\s+librar", "district\\\\s+librar"]},
    {"tag": "digital_library", "label": "Digital libraries", "patterns": ["digital\\\\s+librar", "National\\\\s+Digital\\\\s+Library"]}
  ],
  "fallback_tag": "topic_match"
}
```

Search groups control what the APIs are queried for. Tag rules control what is
kept, labeled, scored, and exported.

## Output Layout

```text
data/libraries/
  manifest.jsonl       normalized crawl records
  analysis.jsonl       parsed/scored records
  summary.json         aggregate export
  crawl.log
  parse.log
  pdfs/ls/*.pdf
  pdfs/rs/*.pdf
  text/*.txt
```

## Commands

```bash
python -m sansad_semantic_crawler crawl --help
python -m sansad_semantic_crawler parse --help
python -m sansad_semantic_crawler export --help
```

## Design Notes

- No required third-party dependency for crawling. If `requests` is installed,
  it is used; otherwise the crawler falls back to `urllib`.
- `pdfminer.six` is optional. `pdftotext` is preferred because parliamentary
  PDFs often rely on layout.
- The crawler is polite by default and sleeps between requests.
- `--max-buckets` and `--max-records` are smoke-test brakes. Use them before a
  full crawl.

## Reuse Pattern

1. Copy this directory into another repo.
2. Add a new `examples/topics/<topic>.json` profile.
3. Run a capped dry crawl.
4. Inspect `manifest.jsonl`.
5. Run a full crawl/download.
6. Parse and export JSON/JS into the host project.

