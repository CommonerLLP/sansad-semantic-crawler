# Sansad Semantic Crawler

A self-contained, config-driven crawler for Indian Parliament — questions
in Lok Sabha and Rajya Sabha, and standing-committee reports — across
arbitrary topics. The package knows the Lok Sabha DSpace API
(`elibrary.sansad.in`), the Rajya Sabha question API (`rsdoc.nic.in`),
and the LS/RS committee-report APIs on `sansad.in`; the *topic logic* —
what to search for, what to tag, what to keep — lives in JSON profiles,
so other projects can add or extend subjects without editing crawler
code.

A topic profile is not a neutral filter. It is a theory of how Parliament
speaks about a subject — which words show up, which ministries field the
question, which language the analysis is conducted in. The crawler treats
profiles as such: each crawl run hashes the profile and writes the hash
alongside the records it produced, so a record cannot be read apart from
the apparatus that produced it.

The package was extracted from
[whoseuniversity.org](https://whoseuniversity.org/)'s parliamentary
research pipeline. It is shared as a public good for civic-tech and
public-interest research; commercial use is not permitted (see
[Licence](#licence) below).

## What it does

- Crawls Lok Sabha questions from `elibrary.sansad.in`.
- Crawls Rajya Sabha questions from `rsdoc.nic.in`.
- Crawls standing-committee reports from `sansad.in/api_ls/committee/`
  and `sansad.in/api_rs/committee/` (16 LS DRSCs + 8 RS DRSCs). Records
  carry a `kind: "committee_report"` field, distinguish original reports
  from Action-Taken Reports (`report_type`), and surface where the report
  has been laid (`presented_via`: `speaker_only` / `ls_only` / `rs_only` /
  `both_houses`) — these are political distinctions, not metadata.
- Normalises every house and every kind into one JSONL manifest with a
  stable composite key, so re-running the crawler resumes cleanly from
  where it left off.
- Optionally downloads each answer's or report's PDF.
- Extracts text from PDFs with `pdftotext -layout` (preferred for
  layout-heavy parliamentary tables), falling back to `pdfminer.six`
  when `pdftotext` is unavailable.
- Classifies every record with one of four modes: deterministic regex
  rules, embedding-anchor similarity, LLM JSON tagging, or an ensemble.
  Every record stamps `language_classified` so consumers know which
  languages were actually examined (today: English-only).
- Writes one record to `_runs.jsonl` per crawl invocation containing the
  topic-profile content hash, classifier mode, scope, and counts. Records
  carry a `run_id` linking them back; the categorical apparatus and the
  data it produced are inseparable.
- Exports a reusable summary as JSON or as a browser-ready
  `window.<NAME>` JS file for static sites.

## What this is — and isn't

This tool builds *corpora*. It does not build accountability. Visibility
of parliamentary outputs is not the same as comprehension of them, and
making committee reports browsable is a different act from making them
consequential. Two things follow.

- **"Audit-grade" here means deterministic and traceable, not
  authoritative.** The regex classifier always produces the same output
  for the same input, and `_runs.jsonl` records exactly which profile
  bytes produced which records. That property is real and useful. It is
  not a substitute for reading the report.
- **Topic-tag matches are about words, not about subjects.** A
  committee report whose title does not mention libraries can still
  concern libraries; a title that does can be tangential. The classifier
  reports its working out (`matches`, `score`); consumers should treat
  these as a triage signal, not a verdict.

The tool's primary users are researchers building topic-specific corpora
of parliamentary text, and the static-site builders that present those
corpora. It is not a watchdog, a summariser, or a search engine.

## Install

The package is not on PyPI yet (publication is planned for a future
release). Install directly from the GitHub release tag:

```bash
pip install "sansad-semantic-crawler @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v0.3.0"

# Optional extras (pick what you need):
pip install "sansad-semantic-crawler[http] @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v0.3.0"           # use `requests` instead of stdlib `urllib`
pip install "sansad-semantic-crawler[pdf] @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v0.3.0"            # pdfminer.six fallback
pip install "sansad-semantic-crawler[embeddings] @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v0.3.0"     # Sentence Transformers models
pip install "sansad-semantic-crawler[llm] @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v0.3.0"            # local chat-completions model-server tagging
pip install "sansad-semantic-crawler[all] @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v0.3.0"            # all optional integrations
```

For a project, pin the same line in your `requirements.txt`:

```text
sansad-semantic-crawler[http,pdf] @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v0.3.0
```

Once PyPI publication lands, `pip install sansad-semantic-crawler` will
work as the simpler form. Existing pinned `git+https://` lines will
keep working indefinitely.

There are zero required third-party dependencies. The crawler runs on a
clean Python 3.10+ install and falls back to `urllib` for HTTP and to
`pdftotext` (system binary) for PDF extraction.

## Quick start

```bash
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

# Parse PDFs / text and export both analysis + summary JSON.
python -m sansad_semantic_crawler parse  --topic examples/topics/libraries.json --out data/libraries
python -m sansad_semantic_crawler export --topic examples/topics/libraries.json --out data/libraries --format json

# Browser-ready JS export for static sites.
python -m sansad_semantic_crawler export \
  --topic examples/topics/libraries.json \
  --out data/libraries \
  --format js \
  --js-global PARLIAMENT_LIBRARY_DATA \
  --export-path data/libraries/parliament_libraries.js

# Standing-committee reports (Lok Sabha + Rajya Sabha DRSCs). Smoke run:
python -m sansad_semantic_crawler crawl-committees \
  --topic examples/topics/libraries.json \
  --out data/libraries-committees \
  --house ls \
  --committees finance \
  --max-records 2 \
  --no-download

# Full LS+RS committee crawl, both houses, current Lok Sabha:
python -m sansad_semantic_crawler crawl-committees \
  --topic examples/topics/libraries.json \
  --out data/libraries-committees \
  --lok-sabha-no 18
```

After install, the same commands are also available via the
`sansad-crawl` console script.

## Integration smoke tests

The repo includes a tiny checked-in smoke corpus and profiles for all
classifier families:

- `examples/corpora/smoke/manifest.jsonl`
- `examples/topics/libraries.json` for regex
- `examples/topics/libraries_embeddings.json` for a real Sentence
  Transformers model
- `examples/topics/libraries_llm_ollama.json` for a real local Ollama
  model through its chat-completions API

See [`docs/INTEGRATION_SMOKE.md`](docs/INTEGRATION_SMOKE.md) for the
exact commands and expected outputs. Keep those checks manual; they
download model weights and require local services.

## Topic profiles

Profiles are plain JSON files. A minimal profile:

```json
{
  "name": "libraries",
  "description": "Public and institutional library questions",
  "search_groups": {
    "public_library": ["public library", "district library"],
    "digital":        ["digital library", "National Digital Library"]
  },
  "lok_sabha_ministries":      ["CULTURE", "EDUCATION"],
  "rajya_sabha_ministry_likes": ["CULTURE", "EDUCATION"],
  "tag_rules": [
    {"tag": "public_library",  "label": "Public libraries",
     "patterns": ["public\\s+librar", "district\\s+librar"]},
    {"tag": "digital_library", "label": "Digital libraries",
     "patterns": ["digital\\s+librar", "National\\s+Digital\\s+Library"]}
  ],
  "fallback_tag": "topic_match"
}
```

`search_groups` controls what the APIs are queried for.
`lok_sabha_ministries` / `rajya_sabha_ministry_likes` add ministry
filters on each house's API.
`tag_rules` controls the default regex classifier. A `weight` field on
a rule scales its contribution to the per-record score. Existing v0.1
profiles that omit `classifier` continue to use regex mode.

Profiles may also choose an explicit classifier:

```json
{
  "classifier": {
    "mode": "embeddings",
    "embedding_model": "BAAI/bge-m3",
    "anchors": {
      "public_library": ["public library", "district public library"],
      "digital_library": ["digital library", "National Digital Library"]
    },
    "threshold": 0.55,
    "device": "auto"
  }
}
```

```json
{
  "classifier": {
    "mode": "llm",
    "endpoint": "http://localhost:11434/v1",
    "api_key": "ollama",
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "temperature": 0,
    "tag_definitions": {
      "public_library": "Questions about publicly funded public libraries.",
      "digital_library": "Questions about digital library infrastructure."
    }
  }
}
```

```json
{
  "classifier": {
    "mode": "ensemble",
    "combine": "union",
    "members": [
      {"mode": "regex"},
      {
        "mode": "embeddings",
        "embedding_model": "BAAI/bge-m3",
        "anchors": {"public_library": ["public library"]}
      }
    ]
  }
}
```

The CLI can override the profile for quick comparisons:

```bash
python -m sansad_semantic_crawler parse \
  --topic examples/topics/libraries.json \
  --out data/libraries \
  --classifier regex
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the classifier contract.

## Open model menu

The package never ships model weights. For embeddings, documented
open-weight defaults are:

- `BAAI/bge-m3` — MIT; multilingual, long-context default for serious
  retrieval-style classification.
- `intfloat/multilingual-e5-large-instruct` — MIT; instruction-tuned
  multilingual embeddings.
- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` —
  Apache 2.0; small, fast prototype baseline.

For LLM JSON tagging through a local chat-completions endpoint:

- `mistralai/Mistral-7B-Instruct-v0.3` — Apache 2.0.
- `Qwen/Qwen2.5-7B-Instruct` — Apache 2.0.
- `microsoft/Phi-3.5-mini-instruct` — MIT.
- `allenai/OLMo-2-1124-7B-Instruct` — Apache 2.0; note the model
  card's additional terms note before using it in redistributed work.

Restricted-license families such as Llama and Gemma can work through the
generic endpoint, but they are not project defaults.

This repository ships **one example profile** —
[`examples/topics/libraries.json`](examples/topics/libraries.json) —
which is the live profile behind
[theright2read](https://theright2read.org). Profiles for
projects that have a privacy or research-strategy reason to keep their
analytical lens private (e.g. higher-education vacancy research)
typically live in the host project's own repository, gitignored or
otherwise not redistributed; the crawler only needs the path on disk.

## Output layout

```text
data/<topic>/
  manifest.jsonl       normalised crawl records (one per question or report)
  _runs.jsonl          one record per crawl invocation: profile hash,
                       classifier mode, scope, counts, errors. Read this
                       to know which apparatus produced which records.
  analysis.jsonl       parsed + scored records (after `parse`)
  summary.json         aggregate export (after `export`)
  crawl.log
  parse.log
  pdfs/
    ls/*.pdf
    rs/*.pdf
  text/*.txt           extracted PDF text, one file per record
```

Records carry a `run_id` field that maps to a row in `_runs.jsonl`. To
verify which topic-profile bytes produced a record, look up its run.

## Commands

```bash
python -m sansad_semantic_crawler crawl  --help
python -m sansad_semantic_crawler parse  --help
python -m sansad_semantic_crawler export --help
```

## Design notes

- **No required third-party dependency for crawling.** If `requests` is
  installed, it is used; otherwise the crawler uses stdlib `urllib`.
  This keeps the install footprint small for users who only need
  the crawl side.
- **`pdfminer.six` is optional.** `pdftotext` (the system binary) is
  preferred because parliamentary PDFs lean heavily on layout for
  tables; `pdfminer.six` is the fallback.
- **The crawler is polite by default** and sleeps between requests
  (`--sleep 0.25` default).
- **`--max-buckets` and `--max-records` are smoke-test brakes.** Use
  them before a full crawl.
- **Stable keys.** Each record's `key` is derived from
  `(house, qtype, qno, answer-date)` for questions, and from
  `(house, committee, report_no[, lokSabha])` for committee reports.
  Re-running the crawler resumes from `manifest.jsonl` and never
  re-fetches a key it has already seen.
- **Form is data, not metadata.** Where a committee report has been
  laid (Speaker only, Lok Sabha only, both houses) is a political
  distinction with consequences. The crawler surfaces it as
  `presented_via` rather than burying it inside dates the consumer
  must reconstruct. Action-Taken Reports are tagged `report_type:
  "action_taken"` because their genre matters.
- **Categories travel with records.** Every crawl invocation appends one
  row to `_runs.jsonl` with the topic-profile content hash and the
  effective classifier configuration (with secrets redacted). A record
  cannot be read apart from the apparatus that classified it.
- **Hindi titles are stored, not classified.** Records carry both
  English (`title`) and Hindi (`title_hindi`) where the API supplies
  them, but the classifier examines English only. `language_classified`
  on each record names this honestly. Hindi-language analysis is a
  known structural gap; see roadmap.

## Reuse pattern

1. `pip install sansad-semantic-crawler`.
2. Author a topic profile (`my-topic.json`) — start by copying
   `examples/topics/libraries.json` and editing the search groups +
   tag rules.
3. Run a capped dry crawl (`--max-buckets 1 --max-records 5`).
4. Inspect `manifest.jsonl`. Tighten the topic regex or classifier
   anchors/definitions if recall or precision look off.
5. Run a full crawl (with `--max-records` removed) and let the
   resume-key logic dedupe.
6. Run `parse` then `export` into the host project.

## Status and roadmap

This is the **0.6.0** release. Highlights since 0.5.0:

- **LLM second-pass discourse classifier.** A 9th label (`FACTUAL_DISCLOSURE`)
  and an opt-in second tier (`--llm-tier`) that escalates `UNCLASSIFIED` records
  from the regex tier to any OpenAI/Ollama-compatible chat-completions endpoint.
- **Committee PDF URL encoding fix.** Standing-committee URLs containing
  literal spaces in path components (e.g. `Rural Development and
  Panchayati Raj`) now download cleanly. Previously every such PDF
  silently failed with `URL can't contain control characters`.
- **Per-bucket telemetry, Bayesian weighting engine, surface discourse
  classifier, ATR/Q/A pair extraction, entity scaffolding** all
  shipped in 0.5.0 and stable in 0.6.0.

The upcoming **0.7.0** release will focus on cross-referencing ATRs to original
reports, debate-transcript entity extraction, and a regex-tier `regex_v2`
that picks up the "AIM/Ministry acknowledges the views/observations of the
Committee" register surfaced by the v0.6.0 committee-channel research.

Planned for later releases:

- **Hindi-language classification parity.** Today the classifier reads
  English titles only. Real parity needs per-profile `covers_languages`,
  Hindi anchor phrases for embeddings (`bge-m3` already handles
  Devanagari), and Hindi regex with transliteration support. Until
  then, `language_classified: ["en"]` is on every record.
- **Profile assumptions schema.** Optional `assumptions` and `omissions`
  fields on topic profiles, surfaced in `_runs.jsonl` and in `summary.json`,
  so a consumer reading the corpus is told what the profile is *not*
  trying to capture.
- **Action-Taken Report linkage.** Cross-link an ATR to the original
  report it answers, when the title or committee/report number permits.
  The genre distinction is already captured (`report_type`); the
  citation graph is not.
- A **resume-with-date-floor** mode for incremental backfills.
- A small `evaluate` command that scores precision / recall against a
  hand-labelled gold set.
- Optional vector-store export for semantic retrieval workflows.

If you're using the crawler and would like a particular extension,
open an issue at the [repository](https://github.com/CommonerLLP/sansad-semantic-crawler/issues).

## Licence

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/).

Source-available and modifiable for research, education, journalism,
public-interest work, and personal use. **Commercial use is not
permitted under any circumstance.** The full canonical licence text is
in [`LICENSE`](./LICENSE) at the repository root.

### Why PolyForm Noncommercial?

This package was built as a public-interest research tool — the kind of
work that ought to be freely available to academics, journalists, and
civil-society projects, but should not be quietly absorbed into the
revenue base of a commercial intelligence product without conversation.
PolyForm Noncommercial is the cleanest off-the-shelf license for that
posture: explicit "yes" for non-commercial use; explicit "no" for
commercial use; no field-of-use carve-outs to litigate.

Concretely:

- **Researchers, students, journalists, and public-interest projects:**
  use it freely, including modification and redistribution. Citation is
  appreciated; see `CITATION.cff`.
- **Commercial entities** (any for-profit organisation, including the
  internal tooling of one): the licence does not grant you use rights.
  If you have a use case that arguably sits in a grey area, contact the
  maintainer and we will sort it out — typically yes for genuinely
  public-interest carve-outs inside commercial orgs (e.g. a newsroom
  inside a for-profit publisher), no for product features.

If you need a commercial license, open an issue marked
`[license inquiry]` and we will respond.

## Citation

A `CITATION.cff` at the repository root carries machine-readable
metadata; GitHub renders a "Cite this repository" button against it.
The maintainer-recommended citation is:

> Commoner LLP. *Sansad Semantic Crawler — reading the Indian
> parliamentary record(s).* 2026.
> <https://github.com/CommonerLLP/sansad-semantic-crawler>.
