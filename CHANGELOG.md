# Changelog

All notable changes to `sansad-semantic-crawler` are recorded here. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The full GitHub release notes live at
<https://github.com/CommonerLLP/sansad-semantic-crawler/releases>; this file
is the single canonical timeline for `requirements.txt` consumers and for
researchers who pin a tag and want to know what they are pinning to.

## [Unreleased]

### Changed

- **NeVA state-assembly acquisition delegated to `commoner-probe`
  (`commoner-probe>=0.7.0` required).** `commoner_probe.neva.StateAssemblyCrawler`
  is now the single source of truth for NeVA acquisition (questions, unlisted
  questions, members, papers laid); `neva.py`'s local re-implementation has
  been removed in favor of a thin compatibility wrapper (`NevaStateCrawler`),
  matching the pattern already used for Sansad Q&A and committee acquisition.

## [2.0.0] — 2026-06-25

### Changed

- **BREAKING — acquisition is delegated to the published `commoner-probe`
  package, now a required dependency (`commoner-probe>=0.5.1`).** The former
  "zero required third-party dependencies" guarantee no longer holds: there is
  no stdlib-only crawl path. Question (LS/RS), committee-report,
  answer-extraction, and member-roster acquisition now live in `commoner-probe`
  as the single source of truth; `sansad-semantic-crawler` keeps only its
  semantic-classification layer. For questions that layer runs at acquisition
  time via the probe's `record_filter_fn` (new in commoner-probe 0.5.1), so
  `--max-records` and the per-run/per-bucket counts reflect topic-matching rows.
  Consumers that pin a tag must ensure `commoner-probe>=0.5.1` is installed.

### Added

- **`sansad-crawl crawl-bills` and `sansad-crawl crawl-debates`** — acquire
  Parliament bill and debate records, delegating to `commoner-probe`.
- **Voice and agency analysis** (`discourse.py`, `aggregations.py`): additive
  surface-analysis fields on `analysis_discourse.jsonl` — `voice`,
  `passive_ratio`, `agent_named`, and `agent_terms` — plus aggregate ministry /
  committee summary fields `mean_passive_ratio` and `agent_named_rate`. This
  extends the discourse layer from *what* the response does to *how* it is
  phrased.

### Removed

- The local fallback crawlers (`_LocalSansadCrawler`, `_LocalCommitteeCrawler`)
  and the duplicated acquisition helpers, constants, and committee catalogs —
  all now sourced from `commoner-probe`.

## [1.1.0] — 2026-05-11

### Added

- **SQLite graph layer** (`graph.py`, `sansad-crawl build-graph`): zero-dependency
  read index over the JSONL pipeline outputs (`answers.jsonl`,
  `analysis_discourse.jsonl`, `entities/people.jsonl`, `atr_linkage.jsonl`).
  SHA-256 hash-based idempotency — rebuild is skipped if inputs are unchanged.
  Schema: `entities`, `memberships`, `questions`, `classifications`,
  `atr_linkages`, `_meta`. Indexed on `ministry`, `asker_key`, `house`,
  `label`, `entity name`. (#34)

- **Regex_v2 coverage expansion** (`discourse.py`): 12 new patterns mined from
  Azad corpus UNCLASSIFIED records. Coverage on the Azad
  (affirmative-action) corpus: 28% → 91.4%. New patterns across `ABSORBED`,
  `FEDERAL_DEFLECTION`, `SUBSTITUTED`, and `SCOPE_NARROWED` labels.
  12 new test cases added. (#33)

- **Security policy** (`SECURITY.md`): disclosure process, supported-version
  policy, and package security scope for the public repo. (#39)

### Tests

381 passing, 1 skipped (up from 355 at v1.0.0).

### Pull requests

- [#33] feat: Regex_v2 coverage expansion
- [#34] feat: SQLite graph layer
- [#39] chore: add SECURITY.md

## [1.0.0] — 2026-05-10

### Changed

- **Schema change:** Renamed `political_function` field to `audit_description` in `analysis_discourse.jsonl` to align with the systemic audit framing.
- **Terminological Reframing:** Retired "Technical Sovereignty" in favor of "Analytical Debt" and "Technical Maturity".
- **Toning Down Performance:** Reframed "Reconstructive Audit" to "Systemic Audit" and removed performative ambedkarite language from code comments and dossier headers.

### Added

- **v1.0.0 Synthesis:** Technical completion of ATR Linkage Engine and functional instrumentation of Constitutional Audit Pipeline.


### What ships: The Audit Pipeline

| Feature | Function | Strategic Purpose |
| :--- | :--- | :--- |
| **Constitutional Defaults** | Proactive detection of Article 16 compliance gaps | Identifying data omission in 'Mission Mode' |
| **Instrumented Discourse** | Verbatim regex tier for bureaucratic evasion | Internalizing technical debt in elite prose |
| **ATR Linkage Engine** | Bidirectional mapping of committee recommendations | Breaking the executive's 'Loop of Opacity' |
| **Ministry Dossiers** | Automated 'Audit Reports' for institutional review | Dismantling the barriers to data access |
| **Structural Agent Toolkit** | Five specialized skills for structural/spatial audit | Grounding automation in a rigorous analytical framework |

### Instrumented Discourse: v2 Regex Tier

The discourse classifier has been refined to identify internal institutional patterns. The v2 regex tier achieves high analytical coverage by internalizing 200+ LLM-tier findings.

| Label | Detection Pattern | Audit Function |
| :--- | :--- | :--- |
| `CONSTITUTIONAL_DEFAULT` | Mission Mode aggregates, PFMS totals | Identification of representation data omission |
| `FEDERAL_DEFLECTION` | 'State Subject' jurisdictional dodges | Mapping the blockade on national accountability |
| `STRUCTURAL_REFUSAL` | Blunt 'No scheme/No approval' responses | Capturing the refusal to establish social democratic infrastructure |
| `REPRESENTATIONAL_SILENCE` | Statistical reciting ignoring Article 16 | Auditing the omission of categorical data |

### Live Audit Coverage

As a proof-of-concept, the v1.0.0 pipeline was applied to the **Education Committee Recruitment ATRs** (n=283 interaction pairs).

- **Data Omission Rate:** Identified **9 specific instances** of `CONSTITUTIONAL_DEFAULT` where statistical substitutions (PFMS) were used to mask faculty reservation gaps.
- **Evasion Patterns:** Detected a pervasive pattern of **`FEDERAL_DEFLECTION`** (12%) and **`SUBSTITUTED`** metrics (5%) used to neutralize parliamentary inquiry.

### Tests

Quality assurance for v1.0.0 involved an exhaustive audit of the representational standards.

- **Total Passing Tests:** 355
- **New Coverage:** Added 42 tests covering ATR structural extraction, verbatim fidelity of multi-part rejections, and the interdependent constraints in the dossier renderer.

### Compatibility

Backward compatible. Schema-additive: existing Q/A and metadata fields remain unchanged.

### Pull requests

- [#29] chore: gitignore root-level private docs (guardrails)
- [#30] feat: instrument discourse classifier for v1.0.0
- [#31] feat: add structural audit scripts and refined ATR engine

## [0.6.6] — 2026-05-09

### Added — structured Q/A sub-fields

`split_qa()` has emitted full `question_text` / `answer_text` halves
since v0.5.0; this release adds *structured* sub-fields stripped of
PDF boilerplate so embedding-based search has clean text to index in
v0.7.0.

Five new additive sub-fields on Q/A records in `answers.jsonl`:

- `question_subject` — the all-caps topic line (e.g. `"ANNUAL INCOME OF SHGS"`)
- `question_stem` — `"Will the Minister of X be pleased to state:"`
- `question_body` — the (a) / (b) / (c) / (d) sub-questions
- `answer_minister_name` — extracted from the `(NAME)` paren in the
  answer prelude
- `answer_body` — answer text with the minister-name preamble stripped

Each parser is best-effort. When its anchor isn't found, the field is
**omitted** from `to_record()` rather than emitted as an empty-string
placeholder that would lie about presence. Legacy `question_text` and
`answer_text` are unchanged.

On a representative LS Q/A corpus, `answer_minister_name` extracts cleanly on the large majority of PDFs; `question_subject` and `question_stem` extract on the subset of PDFs that follow the canonical "Will the Minister of X be pleased to state:" form. PDFs that depart from this form fall through with the relevant fields omitted, rather than emitted as empty placeholders.

### Tests

313 tests passing (up from 299). 14 new tests in `tests/test_qa_structured_parse.py`.

### Compatibility

Backward compatible. Schema-additive: existing fields unchanged.

### Pull requests

- [#27] feat(v0.6.5): structured Q/A sub-fields

## [0.6.4] — 2026-05-09

### Added — research-assistant CLI trio

Three new CLI subcommands that turn ad-hoc demo queries into reproducible
artifacts. Each is small, reads existing JSONL outputs, carries
`topic_hash` provenance, and is independently useful.

- **`extract-atr-linkage`** — for every Action Taken Report in
  `manifest.jsonl`, parses the title to find the original report it
  cites; writes `atr_linkage.jsonl`. Handles three real-corpus title
  variants (digit-at-anchor, word-at-anchor like
  `"Three Hundred And Sixty Sixth Report"`, and the older
  `"Report No. N"` form). Anchored matching against
  `"contained in the"` is required because the ATR's own number
  appears earlier in the title than the referenced one. Output rows
  carry `references_report_no` plus the computed
  `references_report_key` for direct join into `manifest.jsonl`. The
  anchored matcher recovers a substantial majority of ATRs that a
  naive regex misses.
- **`mp-summary`** — aggregates per-MP question count, ministries
  asked, and response-label distribution. Keys by stable `entity_id`
  when the resolver was used; falls back to a name-based key. Each
  row carries party, state, house, `substantive_count`,
  `evasive_count`, and `evasion_rate_classified`. Skips committee
  records (no single asker). Output: `mp_summary.jsonl`.
- **`analyse-ministry`** — aggregates per-ministry (Q/A channel) and
  per-committee (committee channel) response patterns. Two output
  files: `ministry_summary_qa.jsonl` and
  `ministry_summary_committee.jsonl`. Each row carries a
  `per_evasion_label_share` field — what fraction of evasive
  responses are DEFLECTED vs DATA_WITHHELD vs SUBSTITUTED — i.e. the
  *grammar* of evasion, not just its rate. Committee rows also
  itemise `rejected_recommendation_keys` so a researcher can trace
  specific recommendations the ministry refused.

### Why this matters

These three turn the crawler into a reusable research instrument.
With a corpus on disk, a researcher can run `mp-summary` to aggregate
question counts and response-label distributions per MP, then
`analyse-ministry` to identify ministries with structural evasion
patterns, then `extract-atr-linkage` to follow specific recommendations
through their committee → ATR life cycle. All three subcommands
operate on existing JSONL — no re-crawl required.

### Tests

299 tests passing (up from 267). 19 new tests pinning anchor
priority, words-form number conversion, entity_id vs name fallback,
evasion-rate edge cases, and qa / committee output separation.

### Compatibility

Backward compatible. New CLI subcommands; nothing existing changes.

### Pull requests

- [#25] feat: research-assistant CLI trio

## [0.6.3] — 2026-05-09

### Added

- **Four-way committee `report_type` taxonomy.** Pre-v0.6.3 the
  classifier was binary (`action_taken` vs `original`); everything
  non-ATR was lumped into one bucket and downstream every numbered
  observation got tagged `dfg_recommendation` regardless of source.
  Now `_report_type()` returns one of:
  - `action_taken` — government's response to earlier
    recommendations
  - `demands_for_grants` — annual ministry-level budget scrutiny
  - `bill` — clause-by-clause legislative review
  - `subject` — own-initiative policy investigation
  - `other` — title doesn't match any pattern (intentionally
    distinct from `subject` so the absence of a classifier is
    visible to consumers)
- **`source_report_type` field on extracted observation records.**
  `answers.jsonl` records now carry the manifest's `report_type`
  forward, so consumers can filter observations by their true
  source (DFG vs Bill vs Subject vs Other) rather than treating all
  non-ATR records as DFG.
- **`REPORT_TYPE_*` public constants + `REPORT_TYPES_KNOWN` frozenset**
  exported from `committees.py` as a single source of truth for
  downstream import.

### Why this matters

India's 24 Departmentally Related Standing Committees produce four
functionally distinct kinds of report. Conflating them loses the
distinction between budget accountability, legislative scrutiny, and
own-initiative policy investigation — which are different forms of
legislative control over the executive. Researchers studying any one
of these dimensions need a clean filter.

On a representative committee-report corpus, all five categories
appear, with `action_taken` and `demands_for_grants` typically the
two largest buckets, `subject` and `bill` smaller, and a residual
`other` for programme-name titles ("Pradhan Mantri Gram Sadak Yojana",
etc.) that don't match any of the four pattern groups. Specific
distributions vary by which committees and time window are crawled.

### Compatibility

- **Backward compatible.** Existing manifests with
  `report_type='original'` continue to dispatch correctly through
  `extract-answers` (legacy value treated as non-ATR observations).
- Callers filtering on `report_type == 'action_taken'` are unchanged.
- Callers filtering on `report_type == 'original'` should bump to
  the finer-grained values — that filter was never correct anyway
  since it lumped three distinct categories.

### Tests

267 tests passing (up from 243). 24 new tests in
`tests/test_report_type.py` covering all 4 categories with real
sansad.in title fixtures, priority-order pinning, and false-positive
guards (`billion`/`billboard` don't match the Bill pattern).

### Pull requests

- [#23] feat: four-way committee report_type taxonomy

## [0.6.2] — 2026-05-09

Security follow-up to v0.6.1 addressing two findings from automated
review of PR #19.

### Fixed (security)

- **P1 (high) — `--llm-block-private` was bypassable via DNS.**
  `_validate_llm_endpoint` previously only blocked IP literals and a
  hardcoded set of loopback names. A hostname (e.g.
  `metadata.attacker.example` resolving to `169.254.169.254`, or
  `internal.corp.local` resolving to `10.0.0.5`) was waved through.
  Now when `allow_private=False`, we resolve the hostname via
  `socket.getaddrinfo` and reject if any returned address is private,
  loopback, link-local, multicast, reserved, or unspecified. DNS
  resolution failures also refuse (rather than fall through and let
  urllib resolve, which would bypass the policy). DNS resolution is
  skipped when `allow_private=True` so the local-Ollama zero-config
  path pays no latency cost.
- **P2 (medium) — `_parse_llm_json` greedy regex broke on multi-object
  responses.** v0.6.1's `\{.*\}` fix for nested objects created a
  regression: a response with the answer plus a trailing example
  (`{"label": "X"} ... {"label": "EXAMPLE"}`) matched from first `{`
  to last `}` and `json.loads` choked. Replaced with
  `json.JSONDecoder().raw_decode()` which walks JSON grammar and
  returns the first valid value, ignoring trailing content.

### Changed

- Style: `tests/test_security_hardening.py` switched from mixed
  `import unittest` + `from unittest import mock` to
  `import unittest.mock as mock`.
- `discourse.py` `except ValueError: pass` got an explanatory comment.

### Tests

243 tests (up from 232).

### Compatibility

Backward compatible. No CLI surface change; no schema change.
Recommended for any deployment using `--llm-tier --llm-block-private`,
since the P1 fix closes the DNS bypass that made the flag
incomplete.

### Pull requests

- [#21] fix: resolve hostnames + balanced JSON parse in LLM tier

## [0.6.1] — 2026-05-09

Security patch release. Addresses six findings (three high, three
medium) from a post-v0.6.0 security review of the LLM tier (introduced
in v0.6.0) and the legacy crawler download paths.

### Fixed (security)

- **H1: SSRF / local-file disclosure in LLM endpoint** —
  `classify_response_llm()` now validates the endpoint scheme against
  an HTTP(S) allowlist before dispatching. Previously `file://`,
  `ftp://`, `gopher://` and other urllib-supported schemes were
  reachable, so a malicious topic-config endpoint string could read
  local files via `urlopen` and have the bytes parsed as JSON. New
  `--llm-block-private` CLI flag rejects loopback / private /
  link-local hosts for hardened deployments.
- **H2: `_REDACT_KEYS` was an exact-name match against
  `{api_key, authorization, token}`.** Anything else (`apiKey`,
  `OPENAI_API_KEY`, `secret`, `client_secret`, `access_token`,
  `bearer_token`, `password`, `credential`) was written verbatim to
  `_runs.jsonl`, which sister projects pin and redistribute. Replaced
  with substring-based `_is_secret_key` check.
- **H3: hardcoded `Authorization: Bearer local`** in
  `_discourse_http_post`. Now accepts an `api_key` parameter with
  `env:VAR_NAME` indirection (matching the convention in
  `classifiers/llm.py`) and only sends the `Authorization` header
  when a key is supplied. New `--llm-api-key` CLI flag.
- **M1: PDF dest_path traversal** — sansad.in API field values
  (`reportNo`, `uuid`, `qslno`) were interpolated raw into f-strings
  building filenames. A malicious upstream returning `../../evil`
  for one of these would have caused `write_pdf` to write outside
  the intended `pdfs/` directory. New `safe_filename_segment()`
  helper applied at all four PDF filename construction sites.
- **M2: `_parse_llm_json` fallback regex broke on nested objects.**
  Changed `\{[^{}]*\}` → `\{.*\}` (matching `classifiers/llm.py`).
- **M4: exception text leaked into public output.** The
  `audit_description` field in `analysis_discourse.jsonl` was
  embedding `f"LLM tier failed: {str(exc)[:80]}"`. Combined with H1
  this would have leaked SSRF response fragments into the public
  corpus. Now emits a categorical message only.

### Added

- `tests/test_security_hardening.py` — 11 regression tests pinning
  each finding above against future drift.
- `safe_filename_segment()` helper exported from `base.py` for any
  future consumer that needs to write paths from upstream API data.
- `--llm-api-key` CLI flag on `analyse-discourse` (supports
  `env:VAR_NAME` indirection).
- `--llm-block-private` CLI flag on `analyse-discourse` for hardened
  deployments that should never call out to private/loopback hosts.

### Documented

8 architecture findings surfaced by the same review pass have been
filed for follow-up in v0.7.0 (channel-as-string fragility, `regex_v1`
name collision, weighting LLM-row stratification, duplicate HTTP layer
between `discourse.py` and `classifiers/llm.py`, hand-pinned
`TOOL_VERSION`, naive datetime, missing `topic_hash` in
`analysis_discourse.jsonl`, `export.py` blindness to discourse layer).

### Tests

232 tests (up from 221).

### Compatibility

- **Backward compatible.** All v0.6.0 CLI flags continue to work
  unchanged; new flags default to current behaviour.
- **Schema-additive:** new error reasons in `audit_description` are
  shorter/categorical but the field type and presence are unchanged.
- **Consumers** pinning `@v0.6.0` continue to work. Bumping to
  `@v0.6.1` is recommended for any deployment that uses the
  `--llm-tier`, since H1/H2/H3 affect the security boundary of the
  LLM tier specifically.

### Pull requests

- [#19] fix: security hardening for LLM tier + crawler download paths

## [0.6.0] — 2026-05-09

### Added

- **LLM second-pass discourse classifier.** Opt-in `--llm-tier` flag on
  `analyse-discourse` escalates `UNCLASSIFIED` records from the regex
  tier to any OpenAI/Ollama-compatible chat-completions endpoint.
  Defaults: `http://localhost:11434/v1` with model `qwen2.5:7b`.
  New CLI flags: `--llm-tier`, `--llm-endpoint`, `--llm-model`,
  `--llm-timeout`. Falls back to `UNCLASSIFIED` (with an error note in
  `audit_description`) on any network or parse failure — never raises.
- **9th discourse label `FACTUAL_DISCLOSURE`.** Direct factual
  recitation without evasion, new commitment, or withholding. LLM-tier
  only; the regex tier does not fire this label.
- **`LLM_CLASSIFIER_VERSION = 'llm_discourse_v1'`** stamped on every
  LLM-tier output for traceability against the regex-tier
  `regex_v1`.
- **`AnalysisStats` gains `llm_classified` and `llm_unresolved`**
  counters.
- **Public `DISCOURSE_LABEL_DESCRIPTIONS`** dict exposes all 9 label
  descriptions for notebooks and external tooling.
- `tests/test_discourse_llm.py` (22 tests) covering the LLM-tier
  classifier, label taxonomy, and corpus-dispatcher integration.
- `tests/test_url_encoding.py` (5 tests) covering the new
  `_encode_url_path` helper.
- `CONTRIBUTING.md` Development setup section explaining the macOS
  Homebrew + Python 3.14 / pytest install pitfall and naming Python
  3.13 as the canonical interpreter for the test suite.

### Fixed

- **Committee PDF URLs are now percent-encoded before HTTP request.**
  sansad.in's committee endpoints embed committee names with literal
  spaces in the path (e.g.
  `/lsscommittee/Rural Development and Panchayati Raj/...`). Both
  `urllib` and `requests` reject URLs with raw spaces; every committee
  PDF download was silently failing with `URL can't contain control
  characters`. Adds `_encode_url_path` helper that percent-encodes
  path/query while staying idempotent on already-encoded URLs.
- **`sansad_semantic_crawler.__version__` returns `'0.6.0'`.** Was
  reporting `'0.2.0'` since the 0.3.0 release — the constant in
  `__init__.py` was never bumped.

### Compatibility

- **Backward compatible.** All v0.5.0 APIs and CLI flags continue to
  work unchanged. The LLM tier is opt-in (default off); existing
  callers see no behaviour change.
- **No new required dependencies.** The LLM tier uses stdlib `urllib`
  to talk to OpenAI/Ollama-compatible endpoints — no SDK pulled in.
- **Schema additions only.** `analysis_discourse.jsonl` records may now
  carry `classifier: 'llm_discourse_v1'` and `label:
  'FACTUAL_DISCLOSURE'` (only when LLM tier is enabled).
- **Consumers** pinning `@v0.5.0` (`theright2read`, `academiaindia`)
  remain compatible. Bump to `@v0.6.0` is opt-in.

### Tests

221 tests (up from 178 in v0.5.0).

### Pull requests

- [#14] feat: LLM second-pass discourse tier
- [#15] docs: document Python 3.13 as canonical test interpreter on macOS
- [#16] fix: percent-encode PDF URLs before HTTP request
- [#17] chore: bump to 0.6.0

## [0.5.0] — 2026-05-09

### Added

- **End-to-end pipeline** from sansad.in to derived political weights:
  `crawl → extract-answers → analyse-discourse → analyse-weights`.
- **Stable entity scaffolding.** `entities/people.jsonl` plus four
  temporal sidecars: `mp_memberships`, `committee_memberships`,
  `ministerial_appointments`, `bureaucratic_postings`. Resolver
  chokepoint maps free-text names to `PERSON_<hash>_<slug>` entity_ids
  with `ambiguous-with-candidates` semantics — never auto-creates
  placeholder entities. Bureaucrat resolution returns
  `status: "deferred"`; schema is reserved.
- **Phase 1 — answer-text extraction.** New `extract-answers` CLI
  parses Q/A and committee report PDFs into structured pairs. Three
  extractors dispatched per `kind`/`report_type`: Q/A →
  `(question, answer)`; ATR → `[(rec_no, recommendation, response),
  ...]`; DFG → `[(rec_no, recommendation), ...]`.
- **Phase 2 — surface discourse classifier.** `analyse-discourse`
  classifies every ministry response by its political function using
  eight locked labels: `ACCEPTED` / `REJECTED` / `SUBSTITUTED` /
  `DEFLECTED` / `ABSORBED` / `DATA_WITHHELD` / `SCOPE_NARROWED` /
  `CIRCULAR_REFERENCE`. Channel-aware priority: Q/A prefers
  `DATA_WITHHELD`/`SCOPE_NARROWED`; committee responses prefer
  `CIRCULAR_REFERENCE`.
- **Phase 4 — Bayesian weighting engine.** `analyse-weights` aggregates
  per-`(person, topic)` and per-`(party, topic)` weights in `[-1, 1]`.
  Bayesian shrinkage toward party prior (`n0=10` default,
  configurable), confidence-weighted aggregation, full provenance
  lineage in every `basis` block.
- **`exclude_patterns` on `tag_rules`** — disambiguation via
  containment-based suppression (an include match is suppressed only
  if some exclude span fully contains it).
- **Per-bucket telemetry in `_runs.jsonl`.** Each `(query, ministry)`
  or `(session, ministry)` bucket records `raw_returned`,
  `after_date_filter`, `kept`, `skipped_seen`, `elapsed_ms`, `error`.
  Empty-result crawls are now debuggable.
- **`--with-entities` flag** on `crawl` triggers MP roster fetch and
  entity-store population. Records carry `asker_entity_ids`,
  `responder_entity_id`, `responder_role_at_event`,
  `language_classified`.
- New CLI subcommands: `extract-answers`, `analyse-discourse`,
  `analyse-weights`.

### Changed

- Suite goes 84 → 178 tests.

### Compatibility

- **Backward compatible.** Existing pinned consumers continue to work
  without code changes — all new fields are additive; existing fields
  unchanged.

## [0.4.0] — 2026-05-08

### Added

- **Automated MP party/state enrichment** for question manifests.
- **Automated committee composition rosters** with API + PDF/LLM
  fallback.
- **Refactored `BaseCrawler`** architecture for shared crawler I/O.

### Changed

- `SansadCrawler.__init__` gains optional `topic_path` and
  `classifier_mode` kwargs (defaulted, backwards-compatible).

## [0.3.0] — 2026-05-08

### Added

- **`crawl-committees` CLI** for LS + RS Department-Related Standing
  Committee reports under the existing topic-profile contract.
- **Per-record provenance.** Every crawl invocation writes one row to
  `_runs.jsonl` containing the topic-profile content hash, classifier
  mode, scope, and errors. Records carry a `run_id` linking back to the
  invocation.
- **`presented_via` and `report_type`** form-as-data fields on
  committee records.
- **`language_classified` on every record** (questions and
  committees) — names the English-only analytic scope honestly.
- **Frozen smoke fixture** under `examples/corpora/committees-smoke/`
  distinguishes parser drift from upstream API drift in tests.

### Compatibility

- All new fields are additive; existing fields unchanged.

## [0.2.0] — 2026-05-06

### Added

- **Pluggable classifiers**: regex (default, back-compat), embeddings
  (sentence-transformers anchor similarity), llm (OpenAI-compatible
  chat-completions JSON tagging), and ensemble (combine modes via
  union / intersection / weighted).
- **Optional pip extras**: `[embeddings]`, `[llm]`, `[all]`. The
  package never ships model weights; users supply their own runtime
  (Ollama, vLLM, llama.cpp server, mlx-lm, transformers, or any hosted
  service that speaks the OpenAI Chat Completions API).
- **Topic-profile schema gains an optional `classifier` block.**
  Profiles that omit it continue to use regex mode; v0.1.0 profiles
  remain valid without modification.

## [0.1.0] — 2026-05-04

### Added

- Initial release. Configuration-driven crawler for Indian Parliament
  question corpora (Lok Sabha + Rajya Sabha).
- Topic-profile contract: search groups, ministry filters, regex tag
  rules.
- `crawl`, `parse`, `export` CLI subcommands.
- `manifest.jsonl` and `analysis.jsonl` canonical schemas.
- Resume-safe crawling via per-record stable keys.

[Unreleased]: https://github.com/CommonerLLP/sansad-semantic-crawler/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/CommonerLLP/sansad-semantic-crawler/compare/v1.1.0...v2.0.0
[1.1.0]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v1.1.0
[1.0.0]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v1.0.0
[0.6.6]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v0.6.6
[0.6.5]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v0.6.5
[0.6.4]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v0.6.4
[0.6.3]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v0.6.3
[0.6.2]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v0.6.2
[0.6.1]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v0.6.1
[0.6.0]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v0.6.0
[0.5.0]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v0.5.0
[0.4.0]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v0.4.0
[0.3.0]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v0.3.0
[0.2.0]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v0.2.0
[0.1.0]: https://github.com/CommonerLLP/sansad-semantic-crawler/releases/tag/v0.1.0

[#14]: https://github.com/CommonerLLP/sansad-semantic-crawler/pull/14
[#15]: https://github.com/CommonerLLP/sansad-semantic-crawler/pull/15
[#16]: https://github.com/CommonerLLP/sansad-semantic-crawler/pull/16
[#17]: https://github.com/CommonerLLP/sansad-semantic-crawler/pull/17
[#19]: https://github.com/CommonerLLP/sansad-semantic-crawler/pull/19
[#21]: https://github.com/CommonerLLP/sansad-semantic-crawler/pull/21
[#23]: https://github.com/CommonerLLP/sansad-semantic-crawler/pull/23
[#25]: https://github.com/CommonerLLP/sansad-semantic-crawler/pull/25
[#27]: https://github.com/CommonerLLP/sansad-semantic-crawler/pull/27
