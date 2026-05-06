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
