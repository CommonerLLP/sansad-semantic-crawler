"""Phase 4: weighting engine — derives per-person and per-party weights
from the discourse-classified corpus.

Reads ``manifest.jsonl`` (for asker identity), ``analysis_discourse.jsonl``
(for response classifications), ``entities/people.jsonl`` and
``entities/mp_memberships.jsonl`` (for entity → party lookup). Writes
``weights/person_topic.jsonl`` and ``weights/party_topic.jsonl``.

What the weight measures
========================

For every parliamentary response classified by ``discourse.py``, the
weighting engine asks: **was the state's response substantive or evasive
to this MP's question?**

* **Substantive** (the state engaged honestly): ACCEPTED, REJECTED.
* **Evasive** (counterinsurgency): DEFLECTED, ABSORBED, SUBSTITUTED,
  DATA_WITHHELD, SCOPE_NARROWED, CIRCULAR_REFERENCE.
* **UNCLASSIFIED**: contributes to neither — recorded but not weighted.

A person's weight on a topic is::

    raw_weight = (substantive - evasive) / (substantive + evasive)

bounded in ``[-1, 1]``. ``+1`` = every response was substantive;
``-1`` = every response was evasion; ``0`` = balanced or no engagement.

The weight measures **what kind of accountability response this MP
extracted from the state on this topic** — not (yet) how good their
questions were. Representation-authenticity (corpus signals like
question_specificity, follow_up_rate, cross_session_continuity,
topic_focus_concentration) is a separate dimension scaffolded for
v0.5.1+.

What the engine does NOT (and never should) do
==============================================

* Collapse the seven structural axes (party, ministry, period, etc.)
  into a single score. The differential between axes IS the finding;
  consumers combine the components themselves.
* Author party_alignment values inline. Weights are *measured* from
  observed corpus behaviour. (Annotation-layer overrides exist for
  collaborator priors, but with α=1.0/β=0.0 in v0.5.0 they don't
  contribute yet.)
* Hide its method. Every weight row carries a ``basis`` block with
  the formula version, prior, posterior, sample size, and run lineage.

Bayesian shrinkage
==================

Small-sample weights are pulled toward the party prior (the same
party's overall weight on this topic). Concretely::

    posterior_weight = (effective_n * raw_weight + n0 * prior_weight)
                       / (effective_n + n0)

where ``n0`` is a pseudo-count controlling how aggressively small
samples shrink. Default ``n0 = 10`` — a person with N effective
responses gets weight = (N * raw + 10 * prior) / (N + 10). A person
with N=2 gets a weight ~5/6ths of the way toward party prior; N=50
moves them mostly off the prior.

This is honest about what the corpus can and can't say about an
individual MP from a small sample.

Confidence-weighting
====================

A ``DEFLECTED`` response with classifier confidence 0.5 contributes
0.5 to the evasive count, not 1.0. The classifier already produces
confidence; ignoring it would discard signal.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runlog import topic_hash

WEIGHTING_VERSION = "discourse_v0.5.0_bayesian_shrinkage"

# Discourse-label categorisation. Locked vocabulary — see ``discourse.py``.
SUBSTANTIVE_LABELS: frozenset[str] = frozenset({"ACCEPTED", "REJECTED"})
EVASIVE_LABELS: frozenset[str] = frozenset({
    "DEFLECTED", "ABSORBED", "SUBSTITUTED",
    "DATA_WITHHELD", "SCOPE_NARROWED", "CIRCULAR_REFERENCE",
})

# Bayesian shrinkage strength. Higher = more aggressive pull toward
# party prior for small samples. n0=10 means a person with 10
# effective responses sits halfway between their raw_weight and the
# party prior.
DEFAULT_SHRINKAGE_N0 = 10.0

# Default α/β for the corpus-vs-priors merge formula. α=1.0, β=0.0 means
# weights come entirely from the corpus; an optional external-priors
# layer contributes nothing in v0.5.0. When that layer is activated,
# β goes nonzero and the merge formula takes over.
DEFAULT_ALPHA = 1.0
DEFAULT_BETA = 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


@dataclass
class _ActorCounts:
    """In-flight per-(entity, topic) tally. Confidence-weighted."""
    label_counts: dict[str, float] = field(default_factory=dict)
    engagement_raw_count: int = 0  # raw rows (no confidence weighting)
    contributing_run_ids: set[str] = field(default_factory=set)

    def add(self, label: str, confidence: float, run_id: str | None) -> None:
        self.label_counts[label] = self.label_counts.get(label, 0.0) + confidence
        self.engagement_raw_count += 1
        if run_id:
            self.contributing_run_ids.add(run_id)

    def _split(self) -> tuple[float, float]:
        substantive = sum(self.label_counts.get(lbl, 0.0) for lbl in SUBSTANTIVE_LABELS)
        evasive = sum(self.label_counts.get(lbl, 0.0) for lbl in EVASIVE_LABELS)
        return substantive, evasive

    def raw_weight(self) -> float:
        substantive, evasive = self._split()
        total = substantive + evasive
        if total == 0:
            return 0.0
        return (substantive - evasive) / total

    def effective_n(self) -> float:
        substantive, evasive = self._split()
        return substantive + evasive


def _shrink(raw: float, prior: float, effective_n: float, n0: float) -> float:
    return (effective_n * raw + n0 * prior) / (effective_n + n0)


def _build_entity_party_index(entities_dir: Path) -> dict[str, str]:
    """Map ``entity_id -> party`` from mp_memberships.jsonl. When a
    person has multiple memberships (cross-house, term changes), the
    most recent ``fetched_at`` wins.
    """
    path = entities_dir / "mp_memberships.jsonl"
    if not path.exists():
        return {}
    by_entity: dict[str, tuple[str, str]] = {}  # entity_id -> (party, fetched_at)
    for row in _read_jsonl(path):
        eid = row.get("entity_id")
        party = (row.get("party") or "").strip()
        fetched = row.get("fetched_at") or ""
        if not eid or not party:
            continue
        existing = by_entity.get(eid)
        if existing is None or fetched > existing[1]:
            by_entity[eid] = (party, fetched)
    return {eid: pf[0] for eid, pf in by_entity.items()}


def _build_manifest_index(manifest_path: Path) -> dict[str, list[str]]:
    """Map ``key -> list of asker_entity_ids`` (filtering nulls)."""
    out: dict[str, list[str]] = {}
    for row in _read_jsonl(manifest_path):
        key = row.get("key")
        if not key:
            continue
        eids = [e for e in (row.get("asker_entity_ids") or []) if e]
        out[key] = eids
    return out


@dataclass
class WeightingStats:
    person_rows: int = 0
    party_rows: int = 0
    discourse_records_read: int = 0
    records_unclassifiable: int = 0  # discourse_label is None or UNCLASSIFIED
    records_no_asker_id: int = 0  # asker resolved to null
    records_no_membership: int = 0  # asker has no party in entity table
    contributing_run_ids: int = 0
    topic_name: str = ""
    topic_hash: str = ""
    method: str = WEIGHTING_VERSION
    computed_at: str = ""


# ---------------------------------------------------------------------------
# Public README written next to weights/ on save.
# ---------------------------------------------------------------------------

_WEIGHTS_README = """# weights/

Derived measurement of state-evasion patterns, per topic profile.
Generated by ``sansad_semantic_crawler.weighting``; do not hand-edit.

## Files

| File | What |
|---|---|
| `person_topic.jsonl` | One row per (entity_id, topic). Bayesian-shrunk weight in [-1, 1]. |
| `party_topic.jsonl`  | One row per (party, topic). Aggregate weight, no shrinkage. |

## Weight semantics

For every parliamentary response classified by ``discourse.py``, the
engine asks: **was the state's response substantive or evasive to
this MP's question?**

- **Substantive** (state engaged honestly): ACCEPTED, REJECTED.
- **Evasive** (counterinsurgency grammar): DEFLECTED, ABSORBED,
  SUBSTITUTED, DATA_WITHHELD, SCOPE_NARROWED, CIRCULAR_REFERENCE.
- **UNCLASSIFIED**: not weighted (recorded for transparency).

```
raw_weight = (substantive - evasive) / (substantive + evasive)
```

bounded in [-1, 1].

- `weight = +1` — every response was substantive
- `weight = -1` — every response was evasion
- `weight = 0` — balanced, or no engagement

## What this measures and what it does NOT measure

This is the **state's response quality** to a given person/party's
questions, **not** the asker's own engagement quality. An MP who asks
many sharp questions but is consistently deflected gets a low weight;
that's the state's evasion, not their failure.

The asker's own engagement quality (specificity, follow-up rate,
cross-session continuity, topic-focus concentration) is the
**representation-authenticity** dimension — separate signal,
roadmapped for v0.5.1+.

## Bayesian shrinkage (person_topic only)

Small-sample weights are pulled toward the party prior:

```
posterior = (effective_n * raw_weight + n0 * prior) / (effective_n + n0)
```

Default `n0 = 10`. A person with N=2 effective responses gets weight
~5/6 of the way toward party prior; N=50 moves them mostly off it.
Honest about how much the corpus can say about an individual MP from
small samples.

## Confidence-weighting

A `DEFLECTED` response with classifier confidence 0.5 contributes 0.5
to the evasive count (not 1.0). The classifier already produces
confidence; ignoring it would discard signal.

## Reading a weight row

Each row's `basis` block carries the full lineage:

```json
{
  "entity_id": "PERSON_xxx",
  "topic": "libraries",
  "weight": -0.42,
  "label_counts": {"DEFLECTED": 4.2, "ABSORBED": 2.0, ...},
  "engagement_count": 12,
  "basis": {
    "raw_weight": -0.55,
    "prior_weight": -0.30,
    "posterior_weight": -0.42,
    "effective_n": 8.5,
    "shrinkage_n0": 10,
    "method": "discourse_v0.5.0_bayesian_shrinkage",
    "confidence_weighted": true,
    "alpha_corpus": 1.0,
    "beta_annotation": 0.0,
    "from_run_ids": ["..."],
    "computed_at": "2026-05-08T...",
    "corpus_kinds_included": ["qa_response", "atr_response"],
    "topic_hash": "sha256:..."
  }
}
```

## What's NOT in here

- External-priors contributions to weights (β=0 in v0.5.0; the merge
  formula is reserved). When the optional priors layer is activated,
  β goes nonzero.
- Debate-floor data (the corpus is QA + committee reports only;
  `corpus_kinds_included` records this honestly).
- Hindi-language responses (English-only classifier; `language_classified`
  recorded on each input record).

## Contestability

Weights are not authoritative — they are deterministic-and-traceable.
Anyone can recompute them from the
same `manifest.jsonl` + `analysis_discourse.jsonl` + `entities/` and
the same topic profile (verified by `topic_hash`). Disagreements
about what the apparatus measures are arguments about the topic
profile, the eight discourse labels, or the shrinkage prior — all of
which are visible in the basis.
"""


def compute_weights(
    out_dir: Path,
    *,
    topic_profile_path: Path | str,
    shrinkage_n0: float = DEFAULT_SHRINKAGE_N0,
    log_fn=print,
) -> WeightingStats:
    """Read corpus + entities + topic profile, write weights/{person,party}_topic.jsonl.

    Idempotent: re-running overwrites the output files. The input
    files (manifest, analysis_discourse, entities) are unchanged.
    """
    out_dir = Path(out_dir)
    weights_dir = out_dir / "weights"
    weights_dir.mkdir(parents=True, exist_ok=True)
    (weights_dir / "README.md").write_text(_WEIGHTS_README, encoding="utf-8")

    manifest_path = out_dir / "manifest.jsonl"
    discourse_path = out_dir / "analysis_discourse.jsonl"
    entities_dir = out_dir / "entities"

    topic_profile_path = Path(topic_profile_path)
    topic_name = "unknown"
    try:
        topic_name = json.loads(topic_profile_path.read_text(encoding="utf-8")).get("name", "unknown")
    except Exception:  # noqa: BLE001
        pass

    stats = WeightingStats(
        topic_name=topic_name,
        topic_hash=topic_hash(topic_profile_path) if topic_profile_path.exists() else "sha256:unknown",
        computed_at=_now(),
    )

    if not discourse_path.exists():
        log_fn(f"no analysis_discourse.jsonl at {discourse_path} — run analyse-discourse first")
        return stats

    asker_index = _build_manifest_index(manifest_path)
    party_index = _build_entity_party_index(entities_dir)

    # Aggregate counts per (entity, topic) and per (party, topic).
    # Topic is fixed per run (one weighting per topic profile invocation).
    person: dict[str, _ActorCounts] = defaultdict(_ActorCounts)
    party: dict[str, _ActorCounts] = defaultdict(_ActorCounts)

    discourse_rows = _read_jsonl(discourse_path)
    stats.discourse_records_read = len(discourse_rows)
    all_run_ids: set[str] = set()

    for row in discourse_rows:
        label = row.get("label")
        if not label or label == "UNCLASSIFIED":
            stats.records_unclassifiable += 1
            continue
        confidence = float(row.get("confidence") or 0.0)
        run_id = row.get("run_id")
        if run_id:
            all_run_ids.add(run_id)

        key = row.get("key")
        askers = asker_index.get(key, [])
        if not askers:
            stats.records_no_asker_id += 1
            continue

        for eid in askers:
            person[eid].add(label, confidence, run_id)
            p = party_index.get(eid)
            if p:
                party[p].add(label, confidence, run_id)
            else:
                stats.records_no_membership += 1

    # Compute party priors first (used by person shrinkage).
    party_weights: dict[str, dict[str, Any]] = {}
    for party_name, counts in party.items():
        raw = counts.raw_weight()
        party_weights[party_name] = {
            "party": party_name,
            "topic": topic_name,
            "weight": round(raw, 4),
            "label_counts": {k: round(v, 3) for k, v in counts.label_counts.items()},
            "engagement_count": counts.engagement_raw_count,
            "member_count": sum(1 for eid in person if party_index.get(eid) == party_name),
            "basis": {
                "raw_weight": round(raw, 4),
                "method": f"{WEIGHTING_VERSION}_party_aggregate",
                "confidence_weighted": True,
                "alpha_corpus": DEFAULT_ALPHA,
                "beta_annotation": DEFAULT_BETA,
                "from_run_ids": sorted(counts.contributing_run_ids),
                "computed_at": stats.computed_at,
                "corpus_kinds_included": ["qa_response", "atr_response"],
                "topic_hash": stats.topic_hash,
            },
        }

    # Write party_topic.jsonl.
    party_path = weights_dir / "party_topic.jsonl"
    with party_path.open("w", encoding="utf-8") as f:
        for row in sorted(party_weights.values(), key=lambda r: r["party"]):
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    stats.party_rows = len(party_weights)

    # Compute person weights with shrinkage toward party prior.
    person_path = weights_dir / "person_topic.jsonl"
    with person_path.open("w", encoding="utf-8") as f:
        for eid, counts in sorted(person.items()):
            raw = counts.raw_weight()
            n_eff = counts.effective_n()
            party_name = party_index.get(eid)
            prior = party_weights.get(party_name, {}).get("weight", 0.0) if party_name else 0.0
            posterior = _shrink(raw, prior, n_eff, shrinkage_n0)
            row = {
                "entity_id": eid,
                "topic": topic_name,
                "party": party_name,
                "weight": round(posterior, 4),
                "label_counts": {k: round(v, 3) for k, v in counts.label_counts.items()},
                "engagement_count": counts.engagement_raw_count,
                "basis": {
                    "raw_weight": round(raw, 4),
                    "prior_weight": round(prior, 4),
                    "posterior_weight": round(posterior, 4),
                    "effective_n": round(n_eff, 3),
                    "shrinkage_n0": shrinkage_n0,
                    "method": WEIGHTING_VERSION,
                    "confidence_weighted": True,
                    "alpha_corpus": DEFAULT_ALPHA,
                    "beta_annotation": DEFAULT_BETA,
                    "from_run_ids": sorted(counts.contributing_run_ids),
                    "computed_at": stats.computed_at,
                    "corpus_kinds_included": ["qa_response", "atr_response"],
                    "topic_hash": stats.topic_hash,
                },
            }
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stats.person_rows += 1

    stats.contributing_run_ids = len(all_run_ids)
    log_fn(
        f"weights: person_rows={stats.person_rows} party_rows={stats.party_rows} "
        f"discourse_read={stats.discourse_records_read} unclassified={stats.records_unclassifiable} "
        f"no_asker={stats.records_no_asker_id} no_membership={stats.records_no_membership}"
    )
    return stats
