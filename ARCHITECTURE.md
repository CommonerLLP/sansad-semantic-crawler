# Analysis architecture

`commoner-analyse` separates three jobs:

1. consume Parliament question metadata and PDFs acquired by `commoner-probe`;
2. extract text into one record-level text file;
3. analyse each record through one or more semantic layers.

The outputs are intentionally layered rather than merged into one giant
schema. The same corpus can be read as:

- topic classification (`analysis.jsonl`)
- response discourse analysis (`analysis_discourse.jsonl`)
- voice / agency surface analysis (fields on `analysis_discourse.jsonl`)
- aggregations (`mp_summary.jsonl`, `ministry_summary_*.jsonl`,
  `weights/*.jsonl`)

## Pipeline map

```text
manifest.jsonl
  ├─ parse
  │    -> analysis.jsonl
  ├─ extract-answers
  │    -> answers.jsonl
  ├─ extract-atr-linkage
  │    -> atr_linkage.jsonl
  └─ build-graph
       -> graph.db

answers.jsonl
  └─ analyse-discourse
       -> analysis_discourse.jsonl

analysis_discourse.jsonl
  ├─ analyse-ministry
  │    -> ministry_summary_qa.jsonl
  │    -> ministry_summary_committee.jsonl
  ├─ mp-summary
  │    -> mp_summary.jsonl
  └─ analyse-weights
       -> weights/person_topic.jsonl
       -> weights/party_topic.jsonl
```

## 1. Topic classification modes

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

This layer writes `analysis.jsonl` and is about topic relevance and
thematic tags, not institutional response behaviour.

## 2. Discourse analysis

`analyse-discourse` reads `answers.jsonl` and classifies the response,
not the topic. It is a separate semantic layer with a separate contract.

The current label set includes:

- `CONSTITUTIONAL_DEFAULT`
- `FEDERAL_DEFLECTION`
- `STRUCTURAL_REFUSAL`
- `REPRESENTATIONAL_SILENCE`
- `ACCEPTED`
- `DEFLECTED`
- `ABSORBED`
- `REJECTED`
- `SUBSTITUTED`
- `DATA_WITHHELD`
- `SCOPE_NARROWED`
- `CIRCULAR_REFERENCE`
- `FACTUAL_DISCLOSURE`
- `UNCLASSIFIED`

Two channels are analysed differently:

- `qa` — written parliamentary question answers
- `committee` — ATR / committee response text

`dfg` records pass through with null discourse fields because they are
recommendations without a response yet.

The discourse layer is deterministic by default (`regex_v2`) and may
optionally escalate `UNCLASSIFIED` rows to an LLM second pass.

## 3. Voice and agency analysis

Voice/agency is an additive surface-analysis layer on top of discourse
classification. It does not replace the discourse label; it explains how
the labelled response is phrased.

Per-record fields on `analysis_discourse.jsonl`:

- `voice` — `active`, `passive`, or `mixed`
- `passive_ratio` — ratio of detected passive cues to all detected voice
  cues
- `agent_named` — whether an institutional actor is named
- `agent_terms` — the actor terms found in the response text

These are deterministic heuristics rather than a full parser. The design
goal is a zero-dependency baseline that travels with the package.

## 4. Aggregate analytical outputs

Once `analysis_discourse.jsonl` exists, the package can derive:

- `mp_summary.jsonl` — per-MP counts and discourse-label distribution
- `ministry_summary_qa.jsonl` — per-ministry Q/A label distribution,
  evasion rate, mean passive ratio, and agent-named rate
- `ministry_summary_committee.jsonl` — committee-channel equivalent
- `weights/person_topic.jsonl` and `weights/party_topic.jsonl` —
  shrinkage-based weighted topic scores
- `graph.db` — SQLite read layer that lets consumers query outputs
  without reconstructing joins by hand

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
python -m commoner_analyse parse \
  --topic examples/topics/libraries.json \
  --out data/libraries \
  --classifier regex
```

## Shared LLM HTTP layer

`llm_client.py` is the single implementation of SSRF-guarded endpoint
validation, API-key resolution (`env:VAR_NAME` indirection), the
Ollama-compatible `/chat/completions` POST, and tolerant JSON-from-LLM
parsing. `discourse.py`'s LLM tier and `dossier.py`'s ministry-query
refinement both call it — see `SECURITY.md` for the one classifier mode
(`classifiers/llm.py`) that does not yet route through it.

## Dependency boundary

The base install requires one third-party dependency, `commoner-probe` (the
acquisition engine and single source of truth for crawling). Embeddings and
LLM support are optional extras:

```bash
pip install "commoner-analyse[embeddings]"
pip install "commoner-analyse[llm]"
pip install "commoner-analyse[all]"
```

Importing or running a mode without its extra raises a clear install hint.
