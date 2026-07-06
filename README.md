# Commoner Analyse

A config-driven domain-analysis layer over records that
[`commoner-probe`](https://github.com/CommonerLLP/commoner-probe) acquires
from the Indian Parliament and state legislatures — Lok Sabha and Rajya
Sabha questions, standing-committee reports, and NeVA state-assembly
records — across arbitrary topics. Acquisition is `commoner-probe`'s job;
this package classifies, tags, aggregates, and cross-references what it
acquires. Topic profiles (what to search for, what to tag, what to keep)
live in JSON, so other projects can add or extend subjects without editing
analysis code. The tool's primary users are researchers building
topic-specific corpora of parliamentary text. It is not a watchdog, a
summariser, or a search engine.


## What it does

- Classifies Lok Sabha/Rajya Sabha questions and standing-committee reports
  by topic, using records `commoner-probe` acquires from
  `elibrary.sansad.in`, `rsdoc.nic.in`, and 16 LS DRSCs + 8 RS DRSCs.
Offers the following analytical support:
- **ATR Linkage Engine.** Automatically links Action Taken Reports back to
  original committee recommendations based on title citations, closing the
  accountability loop between instructions and executive action.
- **Instrumented Discourse Tier (v2).** A deterministic response classifier
  refined through LLM-tier analysis of real-world corpora. It assigns
  functional discourse labels such as `CONSTITUTIONAL_DEFAULT`,
  `FEDERAL_DEFLECTION`, `DATA_WITHHELD`, `SCOPE_NARROWED`,
  `SUBSTITUTED`, and `FACTUAL_DISCLOSURE`.
- **Voice and Agency Analysis.** Each discourse row can also carry
  additive surface-analysis fields describing *how* the response is
  written: `voice` (`active` / `passive` / `mixed`), `passive_ratio`,
  `agent_named`, and `agent_terms`.
- **Graph Analyses.** Ingests all pipeline outputs
  into a single SQLite database for fast cross-file queries and graph
  navigation.
- **Audit Generators.** CLI subcommands (`mp-dossier`, `ministry-dossier`)
  that produce Markdown-based briefings and audit reports, quantifying
  data omission rates and institutional default status.

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

## Semantic analyses

The package exposes three distinct analytical layers over the same
corpus. They are intentionally separate because they answer different
questions and produce different outputs.

### 1. Topic classification (`analysis.jsonl`)

This layer answers:

- Is this record about the topic profile I care about?
- Which tags or themes fired?

Depending on the topic profile, the crawler can classify each crawled
record through one of four modes:

- `regex` — deterministic `tag_rules` over titles, question text, answer
  text, or extracted text
- `embeddings` — anchor-phrase similarity against an external Sentence
  Transformers model
- `llm` — JSON tagging against a chat-completions style endpoint
- `ensemble` — unions, intersects, or weights multiple classifier members

This layer writes `analysis.jsonl`. Each row is still a topic-level
classification: `tags`, `matches`, `score`, excerpt, and any
mode-specific metadata.

### 2. Response discourse analysis (`analysis_discourse.jsonl`)

This layer answers:

- What is the political function of the ministry's response?
- Is the answer substantive, evasive, withheld, or jurisdictionally
  narrowed?

It runs on extracted response text, not on raw metadata. It is produced
by the `extract-answers` → `analyse-discourse` path and is separate from
topic tagging.

The current discourse label set is:

- `CONSTITUTIONAL_DEFAULT` — category-wise representation data is omitted
  through aggregate totals or substitution
- `FEDERAL_DEFLECTION` — the response pushes responsibility away through
  a "State Subject" or federalism dodge
- `STRUCTURAL_REFUSAL` — blunt refusal; no scheme, no approval, or no
  willingness to act
- `REPRESENTATIONAL_SILENCE` — factual recitation that strategically
  ignores the representational core of the question
- `ACCEPTED` — concrete commitment with specifics, dates, approvals, or
  allocations
- `DEFLECTED` — indefinite deferral such as "under consideration" or
  "steps are being taken"
- `ABSORBED` — acknowledged without commitment; noted, appreciated, or
  absorbed into procedure
- `REJECTED` — flat disagreement, infeasibility, or rejection of the
  recommendation
- `SUBSTITUTED` — the question's metric is replaced with the ministry's
  preferred framing
- `DATA_WITHHELD` — the response says data is not maintained, not
  available, or still being collected
- `SCOPE_NARROWED` — the response narrows jurisdiction or says the matter
  lies outside the ministry's purview
- `CIRCULAR_REFERENCE` — the committee response points back to its own
  earlier non-answer
- `FACTUAL_DISCLOSURE` — direct factual answer without obvious evasion or
  new commitment
- `UNCLASSIFIED` — no current deterministic pattern matched

Channel matters:

- `qa` is used for written parliamentary question answers
- `committee` is used for ATR / committee-response text
- `dfg` passthrough rows carry null discourse fields because
  recommendations exist before any response does

When enabled, an optional LLM second pass only touches rows the regex
tier left `UNCLASSIFIED`.

### 3. Voice and agency surface analysis

This is an additive layer on top of discourse analysis. It answers:

- Is the response written in active, passive, or mixed voice?
- Does the response name an actor, or erase one?

The per-record fields are:

- `voice` — `active`, `passive`, or `mixed`
- `passive_ratio` — share of detected voice cues that are passive
- `agent_named` — whether an institutional actor is named
- `agent_terms` — the actor terms found, e.g. `"the Ministry"` or
  `"the Central Government"`

This layer is deterministic and dependency-free. It uses conservative
heuristics rather than a full NLP parser so it can ship in the base
package without introducing a heavy runtime dependency.

### What the analytical layers are for

- Use topic classification to decide which records belong in your corpus
  and what themes they carry.
- Use discourse labels to decide what kind of institutional response a
  ministry gave.
- Use voice and agency to decide how explicitly or evasively that
  response is phrased at the sentence surface.

Downstream commands compose these layers rather than recomputing them:

- `analyse-ministry` rolls discourse labels and voice/agency up into
  ministry-level summaries
- `mp-summary` rolls them up by asking MP
- `build-graph` indexes them in SQLite
- the dossier commands turn them into Markdown briefings

## Install

The package is not on PyPI yet (publication is planned for a future
release). Install directly from the GitHub release tag:

```bash
pip install "commoner-analyse @ git+https://github.com/CommonerLLP/commoner-analyse.git@v2.1.0"

# Optional extras (pick what you need):
pip install "commoner-analyse[http] @ git+https://github.com/CommonerLLP/commoner-analyse.git@v2.1.0"
pip install "commoner-analyse[pdf] @ git+https://github.com/CommonerLLP/commoner-analyse.git@v2.1.0"
pip install "commoner-analyse[embeddings] @ git+https://github.com/CommonerLLP/commoner-analyse.git@v2.1.0"
pip install "commoner-analyse[llm] @ git+https://github.com/CommonerLLP/commoner-analyse.git@v2.1.0"
pip install "commoner-analyse[all] @ git+https://github.com/CommonerLLP/commoner-analyse.git@v2.1.0"
```

For a project, pin the same line in your `requirements.txt`:

```text
commoner-analyse[http,pdf] @ git+https://github.com/CommonerLLP/commoner-analyse.git@v2.1.0
```

The one required third-party dependency is `commoner-probe` — the
acquisition engine and single source of truth for crawling. Beyond that the
package runs on a clean Python 3.10+ install: the optional `[http]`/`[pdf]`
extras fall back to `urllib` for HTTP and to `pdftotext` (system binary) for
PDF extraction.

## Quick start

```bash
# Core Pipeline
commoner-analyse crawl             # Fetch metadata and PDFs
commoner-analyse crawl-committees  # Crawl standing-committee reports
commoner-analyse parse             # Topic classification -> analysis.jsonl
commoner-analyse export            # Aggregate for sites
commoner-analyse build-graph       # Ingest pipeline outputs into SQLite

# Response / audit pipeline
commoner-analyse extract-answers      # Response extraction -> answers.jsonl
commoner-analyse analyse-discourse    # Discourse + voice/agency -> analysis_discourse.jsonl
commoner-analyse analyse-weights      # Per-person / per-party weights

# Research / audit subcommands
commoner-analyse extract-atr-linkage  # Map ATRs to original reports
commoner-analyse mp-dossier           # Generate MP-level briefing
commoner-analyse ministry-dossier     # Generate Ministry audit report
commoner-analyse analyse-ministry     # Aggregate evasion patterns
commoner-analyse mp-summary           # Aggregate MP assertion rates
```

## Output layout

```text
data/<topic>/
  manifest.jsonl       normalised crawl records (one per question or report)
  _runs.jsonl          one record per crawl invocation: profile hash,
                       classifier mode, scope, counts, errors. Read this
                       to know which apparatus produced which records.
  analysis.jsonl       topic-level semantic classification (after `parse`)
  answers.jsonl        extracted question/answer or recommendation/response
                       pairs (after `extract-answers`)
  analysis_discourse.jsonl
                       discourse labels + voice/agency analysis over
                       response text (after `analyse-discourse`)
  atr_linkage.jsonl    mapped bidirectional links (after `extract-atr-linkage`)
  mp_summary.jsonl     per-MP discourse summary (after `mp-summary`)
  ministry_summary_qa.jsonl
                       per-ministry Q/A discourse summary
  ministry_summary_committee.jsonl
                       per-committee ATR/committee discourse summary
  weights/
    person_topic.jsonl per-person weighted topic scores
    party_topic.jsonl  per-party weighted topic scores
  graph.db             SQLite read layer over outputs (after `build-graph`)
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
- **Crawling is delegated to `commoner-probe`** — the one required
  third-party dependency and the single source of truth for acquisition.
  Other third-party packages (`requests`, `pdfminer.six`, embeddings/LLM)
  remain optional extras.
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
The latest published release is **v2.0.0**. `main` may move ahead with
additive features before the next tag; check the changelog's
`Unreleased` section for post-release work.

## Licence

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/).

## Citation

A `CITATION.cff` at the repository root carries machine-readable
metadata; GitHub renders a "Cite this repository" button against it.
