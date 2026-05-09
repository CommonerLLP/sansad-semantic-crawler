# Changelog

All notable changes to `sansad-semantic-crawler` are recorded here. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The full GitHub release notes live at
<https://github.com/CommonerLLP/sansad-semantic-crawler/releases>; this file
is the single canonical timeline for `requirements.txt` consumers and for
researchers who pin a tag and want to know what they are pinning to.

## [Unreleased]

Planned for the next release:

- Channel enum + dispatch dict to replace the binary `if channel == CHANNEL_QA`
  fallthrough (architecture review finding; precondition for v0.7.0
  debate-transcript work).
- Rename `regex_v1` constants in `discourse.py` and `answers.py` to
  disambiguate (`discourse_regex_v1` vs `answers_regex_v1`) before
  any external consumer indexes the literal strings.
- ATR-to-original-recommendation cross-linking.
- Debate-transcript entity extraction.
- `regex_v2` discourse classifier picking up the
  "AIM/Ministry acknowledges the views/observations of the Committee"
  register surfaced by the v0.6.0 committee-channel research.
- Per-classifier weight stratification so audit-grade weights survive
  the LLM tier becoming the default.
- Hindi-language classification parity.

## [0.6.6] — 2026-05-09

### Added — `mp-dossier` CLI subcommand (per-MP topic briefing)

The first analyst-facing lever from `notes/ROADMAP.md §IV`: given an MP's
`entity_id` (preferred) or loose `--name`, generate a single Markdown
briefing covering their entire question history on a corpus, grouped
by topic, with the ministerial response-label distribution and
excerpts of evasion text per topic.

The artefact is what the analyst reads to make the bridging-knowledge
call (per `notes/PRODUCT_DESIGN.md §IV`). The crawler does *not*
suggest reframings; it makes the gap visible — *"on libraries, this MP
got SCOPE_NARROWED 3 times"* — so the analyst applies their domain
knowledge to suggest a better framing.

```
sansad-crawl mp-dossier --out <corpus_dir> --entity-id PERSON_xxx
sansad-crawl mp-dossier --out <corpus_dir> --name "Sivadasan"
```

Output: `<corpus_dir>/mp_dossiers/<slug>.md`.

Topic clustering uses keyword overlap on the v0.6.5 `question_subject`
field, normalised by stop-word removal + sorted-token-set keying. No
embeddings — those arrive in v0.7.0 only if v0.6.6 keyword overlap is
demonstrably insufficient. Records without a parsed `question_subject`
fall into a single `"Uncategorised"` bucket rather than being silently
dropped (coverage is honest, not hidden).

The dossier section heading for each topic is the most common original
surface form across the cluster, not whichever record happened to come
last in iteration order.

### Validation posture

🟡 **User-validated, awaiting deployment iteration.** The next step is
to run `mp-dossier` for Sivadasan against a libraries-topic corpus,
hand the Markdown to his office, and iterate based on whether the
output is useful. If unreadable or missing topics he actually cares
about, slip and fix.

### Tests

335 tests passing (up from 313). 22 new tests in
`tests/test_dossier.py` covering topic-key normalisation, loose name
matching, record selection by entity_id and name, Markdown rendering,
empty-corpus handling, `mp_dossiers/` slug derivation, and topic-key
clustering.

## [0.6.5] — 2026-05-09

### Added — structured Q/A sub-fields

First step toward the v0.7.0 `mp-draft` bridge feature for Azad
(per `notes/ROADMAP.md`). `split_qa()` has emitted full
`question_text` / `answer_text` halves since v0.5.0; this release adds
*structured* sub-fields stripped of PDF boilerplate so embedding-based
search has clean text to index in v0.7.0.

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

Live ADP Q/A coverage (n=279): `answer_minister_name` 95%, `question_subject` 33%, `question_stem` 34%. The lower subject/stem rates reflect real corpus variability; about a third of Lok Sabha Q/A PDFs don't follow the canonical "Will the Minister of X be pleased to state:" form.

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
  appears earlier in the title than the referenced one. Live-corpus
  result: 83 / 96 ADP committee ATRs get a linkage extracted (was 31
  with a naive regex). Output rows carry `references_report_no` plus
  the computed `references_report_key` for direct join into
  `manifest.jsonl`.
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
With the live ADP corpus on disk, an opposition MP's research
assistant can now run `mp-summary` to find every question asked on a
topic by party, then `analyse-ministry` to identify the ministries
where evasion is structural, then `extract-atr-linkage` to follow
specific recommendations through their committee → ATR life cycle.
None of this required a re-crawl; all three subcommands operate on
existing JSONL.

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

Live-corpus distribution from the v0.6.0 ADP committee crawl (n=221):
- `action_taken`: 96 (43%)
- `demands_for_grants`: 71 (32%)
- `subject`: 27 (12%)
- `other`: 19 (9%)  — programme-name titles like "Pradhan Mantri
  Gram Sadak Yojana"
- `bill`: 8 (4%)

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
  `political_function` field in `analysis_discourse.jsonl` was
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

- `notes/TECHDEBT.md` — 8 architecture findings from the same review
  pass (channel-as-string fragility, `regex_v1` name collision,
  weighting LLM-row stratification, duplicate HTTP layer between
  `discourse.py` and `classifiers/llm.py`, hand-pinned
  `TOOL_VERSION`, naive datetime, missing `topic_hash` in
  `analysis_discourse.jsonl`, `export.py` blindness to discourse
  layer). Scoped for v0.7.0.

### Tests

232 tests (up from 221).

### Compatibility

- **Backward compatible.** All v0.6.0 CLI flags continue to work
  unchanged; new flags default to current behaviour.
- **Schema-additive:** new error reasons in `political_function` are
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
  `political_function`) on any network or parse failure — never raises.
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

[Unreleased]: https://github.com/CommonerLLP/sansad-semantic-crawler/compare/v0.6.5...HEAD
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
