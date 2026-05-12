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
- **ATR Linkage Engine.** Automatically links Action Taken Reports back to
  original committee recommendations based on title citations, closing the
  accountability loop between instructions and executive action.
- **Instrumented Discourse Tier (v2).** A deterministic regex classifier
  refined through LLM-tier analysis of real-world corpora. Automatically
  tags responses with functional labels: `CONSTITUTIONAL_DEFAULT`,
  `FEDERAL_DEFLECTION`, `DATA_SUBSTITUTION`, and `REPRESENTATIONAL_SILENCE`.
- Normalises every house and every kind into one JSONL manifest with a
  stable composite key, so re-running the crawler resumes cleanly from
  where it left off.
- Optionally downloads each answer's or report's PDF.
- Extracts text from PDFs with `pdftotext -layout` (preferred for
  layout-heavy parliamentary tables), falling back to `pdfminer.six`
  when `pdftotext` is unavailable.
- Classifies every record with one of four modes: deterministic regex
  rules, embedding-anchor similarity, LLM JSON tagging, or an ensemble.
- **SQLite Graph Layer.** Ingests all pipeline outputs (`answers.jsonl`,
  `analysis_discourse.jsonl`, `entities/people.jsonl`, `atr_linkage.jsonl`)
  into a single SQLite database for fast cross-file queries and graph
  navigation. Rebuilds are skipped automatically if inputs are unchanged.
- **Audit Generators.** CLI subcommands (`mp-dossier`, `ministry-dossier`)
  that produce Markdown-based briefings and audit reports, quantifying
  data omission rates and institutional default status.
- Writes one record to `_runs.jsonl` per crawl invocation containing the
  topic-profile content hash, classifier mode, scope, and counts. Records
  carry a `run_id` linking them back; the categorical apparatus and the
  data it produced are inseparable.
- Exports a reusable summary as JSON or as a browser-ready
  `window.<NAME>` JS file for static sites.

## What this is — and isn't

This tool builds *corpora* and *audits*. Visibility of parliamentary
outputs is not the same as comprehension of them.

- **"Audit-grade" here means deterministic, traceable, and linked.**
  The regex classifier always produces the same output for the same
  input, and `_runs.jsonl` records exactly which profile bytes produced
  which records. The addition of the ATR Linkage Engine enables the
  bidirectional tracking of institutional responsibility.
- **Instrumented, not authoritative.** The classification labels are
  technical hypotheses based on linguistic patterns of institutional
  evasion. They are a triage signal for researchers, not a verdict.

The tool's primary users are researchers building topic-specific corpora
of parliamentary text, and the static-site builders that present those
corpora. It is not a watchdog, a summariser, or a search engine.

## Install

The package is not on PyPI yet (publication is planned for a future
release). Install directly from the GitHub release tag:

```bash
pip install "sansad-semantic-crawler @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v1.1.0"

# Optional extras (pick what you need):
pip install "sansad-semantic-crawler[http] @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v1.1.0"
pip install "sansad-semantic-crawler[pdf] @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v1.1.0"
pip install "sansad-semantic-crawler[embeddings] @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v1.1.0"
pip install "sansad-semantic-crawler[llm] @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v1.1.0"
pip install "sansad-semantic-crawler[all] @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v1.1.0"
```

For a project, pin the same line in your `requirements.txt`:

```text
sansad-semantic-crawler[http,pdf] @ git+https://github.com/CommonerLLP/sansad-semantic-crawler.git@v1.1.0
```

There are zero required third-party dependencies. The crawler runs on a
clean Python 3.10+ install and falls back to `urllib` for HTTP and to
`pdftotext` (system binary) for PDF extraction.

## Quick start

```bash
# Core Pipeline
sansad-crawl crawl             # Fetch metadata and PDFs
sansad-crawl crawl-committees  # Crawl standing-committee reports
sansad-crawl parse             # Extract and classify text
sansad-crawl export            # Aggregate for sites
sansad-crawl build-graph       # Ingest pipeline outputs into SQLite

# Audit Subcommands
sansad-crawl extract-atr-linkage  # Map ATRs to original reports
sansad-crawl mp-dossier           # Generate MP-level briefing
sansad-crawl ministry-dossier     # Generate Ministry audit report
sansad-crawl analyse-ministry      # Aggregate evasion patterns
sansad-crawl mp-summary           # Aggregate MP assertion rates
```

## Output layout

```text
data/<topic>/
  manifest.jsonl       normalised crawl records (one per question or report)
  _runs.jsonl          one record per crawl invocation: profile hash,
                       classifier mode, scope, counts, errors. Read this
                       to know which apparatus produced which records.
  analysis.jsonl       parsed + scored records (after `parse`)
  atr_linkage.jsonl    mapped bidirectional links (after `extract-atr-linkage`)
  summary.json         aggregate export (after `export`)
  pdfs/
    ls/*.pdf
    rs/*.pdf
  text/*.txt           extracted PDF text, one file per record
  ministry_dossiers/   Markdown audit reports (after `ministry-dossier`)
  mp_dossiers/         Markdown MP briefings (after `mp-dossier`)
```

Records carry a `run_id` field that maps to a row in `_runs.jsonl`. To
verify which topic-profile bytes produced a record, look up its run.

## Design notes

- **Stability and Maturity.** As of v1.0.0, the core schemas and pipeline
  are stable. The tool prioritizes verbatim fidelity in extraction and
  traceability in classification.
- **No required third-party dependency for crawling.** If `requests` is
  installed, it is used; otherwise the crawler uses stdlib `urllib`.
- **`pdfminer.six` is optional.** `pdftotext` (the system binary) is
  preferred because parliamentary PDFs lean heavily on layout for
  tables; `pdfminer.six` is the fallback.
- **Stable keys.** Each record's `key` is derived from
  `(house, qtype, qno, answer-date)` for questions, and from
  `(house, committee, report_no[, lokSabha])` for committee reports.
- **Form is data, not metadata.** Where a committee report has been
  laid (Speaker only, Lok Sabha only, both houses) is a political
  distinction with consequences. The crawler surfaces it as
  `presented_via` rather than burying it inside dates.

## Status

The full per-release timeline lives in [CHANGELOG.md](CHANGELOG.md).
This is the **1.1.0** release.

## Licence

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/).

## Citation

A `CITATION.cff` at the repository root carries machine-readable
metadata; GitHub renders a "Cite this repository" button against it.
