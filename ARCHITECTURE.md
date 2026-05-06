# Classifier architecture

`sansad-semantic-crawler` separates three jobs:

1. crawl Parliament question metadata and PDFs;
2. extract text into one record-level text file;
3. classify each record through a pluggable classifier.

The crawl, parse, and export commands keep the same file layout across
classifier modes. `analysis.jsonl` always contains `tags`, `matches`, and
`score`; semantic modes also add audit fields such as `classifier`,
`model`, `explain`, and `elapsed_ms` when available.

## Modes

`regex` is the default and remains the audit-grade path. It counts
configured regular expressions from `tag_rules`, applies per-rule weights,
and emits deterministic matches.

`embeddings` embeds the record text and compares it with per-tag anchor
phrases. It is useful for discovery and semantic search-like triage when
the exact language is not known in advance. The package does not ship model
weights; users provide a Hugging Face / Sentence Transformers model id.

`llm` sends the record text and tag definitions to a chat-completions style
endpoint and expects JSON back. It is useful for soft classification and
short explanations. The endpoint can be Ollama, vLLM, llama.cpp server, or
another compatible local/open service. The package uses stdlib HTTP here;
it does not depend on the OpenAI SDK and does not require OpenAI models.

`ensemble` combines classifier outputs by `union`, `intersection`, or
`weighted`. Scores are mode-internal and should not be compared across
classifier types as if they were the same unit.

## Topic profile contract

Existing v0.1 profiles keep working:

```json
{
  "name": "libraries",
  "tag_rules": [
    {"tag": "public_library", "patterns": ["public\\s+librar"]}
  ]
}
```

New profiles can add a classifier block:

```json
{
  "classifier": {
    "mode": "embeddings",
    "embedding_model": "BAAI/bge-m3",
    "anchors": {
      "public_library": ["public library", "district library"]
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
      "public_library": "Questions about publicly funded public libraries."
    }
  }
}
```

The CLI can override the profile for A/B runs:

```bash
python -m sansad_semantic_crawler parse \
  --topic examples/topics/libraries.json \
  --out data/libraries \
  --classifier regex
```

## Dependency boundary

The base install has no required third-party dependencies. Embeddings and
LLM support are optional extras:

```bash
pip install "sansad-semantic-crawler[embeddings]"
pip install "sansad-semantic-crawler[llm]"
pip install "sansad-semantic-crawler[all]"
```

Importing or running a mode without its extra raises a clear install hint.
