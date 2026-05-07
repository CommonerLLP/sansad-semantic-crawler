# Contributing

Thanks for considering a contribution.

This is a small, deliberately scoped public-interest library. The
codebase optimises for stability over feature breadth: the package is
used by sister projects ([freelibraries4all](https://github.com/CommonSenseLLP/freelibraries4all.github.io)
and [academiaindia](https://github.com/CommonSenseLLP/academiaindia))
which pin a specific tag and expect the API surface to behave the same
way for the lifetime of that pin.

Read this whole file before opening a PR; most disagreements with
reviewers are about scope, not code.

## What kind of changes are welcome

- **Bug fixes** in the crawl, parse, or export paths — particularly
  fixes that make `manifest.jsonl` cleaner or `analysis.jsonl` more
  consistent across the four classifier modes.
- **New parser support** for additional Parliament-adjacent sources
  documented in `## Status and roadmap` of the README (standing
  committee reports, etc.) — open an issue first to align on shape.
- **New classifier modes** that fit the existing topic-profile
  contract.
- **Test coverage** for the under-tested classifier modes
  (embeddings, llm, ensemble) and for the crawl resume-key logic.
- **Documentation fixes.**
- **Pure-stdlib improvements** — anything that reduces the surface
  area or sharpens the audit-grade regex path.

## What's deliberately out of scope

- A web UI, a service, a hosted API. The package is a library.
- Bundling model weights. Embeddings and LLM modes accept user-provided
  models. The package is intentionally weight-free.
- Vendor-specific integrations (no OpenAI SDK, no
  HuggingFace-Inference-API as a default). Users who want those build
  on top.
- Rich data-cleaning / NER / named-entity normalisation. Out of scope
  unless someone shows up wanting to maintain it.
- Commercial-friendly relicensing or dual licensing. The PolyForm
  Noncommercial stance is deliberate (see README "Why PolyForm
  Noncommercial?").

If you are unsure whether your proposed change fits, open an issue
describing the change before writing code.

## How to file an issue

A good issue has:

- A short title (under ~70 characters).
- The mode or surface it concerns: `crawl`, `parse`, `export`, or one
  of the classifier modes (`regex`, `embeddings`, `llm`, `ensemble`).
- For bugs: minimal reproduction (a fixture is best — see
  `examples/corpora/smoke/`), expected vs. actual output.
- For new-feature requests: the topic profile or use case driving it.
- For licence questions: tag the title `[license inquiry]`.

Issues that propose features without a use case attached will be
closed.

## How to file a PR

1. Fork to your own GitHub account.
2. Branch off `main`. Branch names follow `<type>/<short-slug>`:
   `fix/lok-sabha-empty-bucket`, `feat/standing-committee-source`,
   `docs/install-line`, `chore/gitignore-private-notes`.
3. Make the change. Keep the diff small — one concern per PR.
4. Run the test suite:
   ```bash
   python -m venv .venv
   .venv/bin/pip install -e ".[all]" pytest
   .venv/bin/pytest -q
   ```
5. If you touched any classifier mode, also run the manual integration
   smoke from `docs/INTEGRATION_SMOKE.md`. Those checks aren't
   automated because they require local model servers and downloads.
6. Open the PR. Link the related issue if there is one. Describe the
   change in two parts: **what** (the diff in plain English) and
   **why** (the use case or bug it addresses).

PRs are merged by the maintainer; please don't merge your own.

## Test expectations

- New classifier modes need at least basic unit coverage of the
  matching path. Mock-based tests are fine; the goal is regression
  detection, not realism.
- New parser sources need a small fixture under
  `examples/corpora/smoke/` and a test that exercises the parse
  path against it.
- The regex classifier is the audit-grade path and must not regress.
  Any change that touches `tag_rules` evaluation requires extra
  scrutiny.

## Versioning and releases

The package follows semantic versioning: `MAJOR.MINOR.PATCH`.

- **PATCH** for bug fixes and documentation.
- **MINOR** for new features (new classifier modes, new sources, new
  config options) that are backward-compatible.
- **MAJOR** for breaking changes to the topic-profile contract or to
  the canonical schema in `manifest.jsonl` / `analysis.jsonl`. We try
  hard to avoid these.

Consumers of this package pin a specific `@v0.X.Y` tag in their
`requirements.txt`. **Do not propose changes that silently break a
pinned consumer.** If a backward-incompatible change is genuinely
necessary, document it in the PR and we will plan a coordinated
upgrade with the known consumers (currently
[freelibraries4all](https://github.com/CommonSenseLLP/freelibraries4all.github.io)
and [academiaindia](https://github.com/CommonSenseLLP/academiaindia)).

## Licence

This project is licensed under
[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/).
By contributing, you agree to license your contribution under the same
terms. See `LICENSE` and the README's "Why PolyForm Noncommercial?"
section for context.

## Questions

Open a GitHub issue. For licence-specific questions, mark the title
`[license inquiry]`.
