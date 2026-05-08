# Integration smoke tests

These checks prove the optional classifier integrations work beyond the
unit-test fakes. They use a tiny checked-in corpus with two positive library
records and one negative-control road/bridge record.

Run from the repository root.

## 1. Create a disposable environment

```bash
python3 -m venv /private/tmp/ssc-integration-venv
/private/tmp/ssc-integration-venv/bin/python -m pip install -e ".[embeddings,llm]"
```

The package itself has no required third-party dependencies. This venv is only
for optional model integration tests.

## 2. Regex baseline

```bash
rm -rf /private/tmp/ssc-smoke-regex
cp -R examples/corpora/smoke /private/tmp/ssc-smoke-regex

/private/tmp/ssc-integration-venv/bin/python -m sansad_semantic_crawler parse \
  --topic examples/topics/libraries.json \
  --out /private/tmp/ssc-smoke-regex \
  --refresh-text
```

Expected: `analysis.jsonl` has three rows with `"classifier": "regex"`.

## 3. Real embeddings model

```bash
rm -rf /private/tmp/ssc-smoke-embeddings
cp -R examples/corpora/smoke /private/tmp/ssc-smoke-embeddings

/private/tmp/ssc-integration-venv/bin/python -m sansad_semantic_crawler parse \
  --topic examples/topics/libraries_embeddings.json \
  --out /private/tmp/ssc-smoke-embeddings \
  --refresh-text
```

Expected:

- rows include `"classifier": "embeddings"`;
- rows include `"model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"`;
- the road/bridge negative-control row has no tags.

The first run downloads the embedding model from Hugging Face.

## 4. Real local LLM through Ollama

Install and start Ollama if needed:

```bash
brew install ollama
ollama serve
```

Pull the small smoke-test model:

```bash
ollama pull qwen2.5:3b-instruct
ollama list
```

Run the parser against Ollama's local chat-completions endpoint:

```bash
rm -rf /private/tmp/ssc-smoke-ollama
cp -R examples/corpora/smoke /private/tmp/ssc-smoke-ollama

/private/tmp/ssc-integration-venv/bin/python -m sansad_semantic_crawler parse \
  --topic examples/topics/libraries_llm_ollama.json \
  --out /private/tmp/ssc-smoke-ollama \
  --refresh-text
```

Expected:

- the public-library row is tagged `public_library`;
- the digital-library row is tagged `digital_library`;
- the road/bridge negative-control row has no tags;
- rows include `"classifier": "llm"`, `"model": "qwen2.5:3b-instruct"`, and `explain`.

Do not put this Ollama smoke in CI. It is a local/manual integration test
because it requires a model server and downloads model weights.

## Standing-committee crawler — frozen fixture

`examples/corpora/committees-smoke/` carries a frozen pair of LS/RS
API responses plus the canonical parser output they should produce.
`tests/test_smoke_fixture.py` runs the crawler against the frozen
payloads with a fake session and asserts the manifest matches.

Running it manually:

```bash
.venv/bin/python -m pytest tests/test_smoke_fixture.py -q
```

To refresh the fixture after a confirmed upstream change:

```bash
# 1. Pull the same two URLs again, overwriting the frozen raw files.
curl -sS \
  -H 'User-Agent: Mozilla/5.0 sansad-semantic-crawler' \
  'https://sansad.in/api_ls/committee/lsRSAllReports?house=L&committeeCode=12&lsNo=18&page=1&size=2&sortOn=reportNo&sortBy=desc' \
  -o examples/corpora/committees-smoke/raw/ls_finance_p1.json

curl -sS \
  -H 'User-Agent: Mozilla/5.0 sansad-semantic-crawler' \
  -H 'Referer: https://sansad.in/rs/committees' \
  'https://sansad.in/api_rs/committee/committee-reports?mstCommId=14&departmentId=&presentationYear=&search=&page=1&size=2&sortOn=reportNo&sortBy=desc&locale=en' \
  -o examples/corpora/committees-smoke/raw/rs_health_p1.json

# 2. Regenerate the canonical manifest from the fresh payloads.
SANSAD_REGENERATE_FIXTURE=1 .venv/bin/python -m pytest tests/test_smoke_fixture.py -q

# 3. Inspect both diffs and commit only intentional changes.
git diff examples/corpora/committees-smoke/
```

Treat the diff in `manifest.jsonl` as itself audit-relevant: which
upstream changes flowed through which parser changes is the kind of
trail Power's *Making Things Auditable* says a tool that calls itself
"audit-grade" ought to preserve.
