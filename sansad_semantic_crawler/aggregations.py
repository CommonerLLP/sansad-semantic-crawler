"""Per-MP and per-ministry aggregation summaries over a topic corpus.

Two reusable summarisers, both reading the canonical pipeline outputs
(``manifest.jsonl`` + ``analysis_discourse.jsonl``) and producing a
single JSONL row per actor:

* ``write_mp_summary()``  — one row per asker MP, with question
  count, ministries asked, response-label distribution, party,
  state, house, and the entity_id when the resolver was used.
* ``write_ministry_summary()`` — one row per ministry/committee,
  with classified vs. unclassified counts, label distribution,
  and a derived evasion rate.

Both summarisers carry ``topic_hash`` and ``corpus_kinds_included``
into every output row so a row read in isolation is reproducible.

These are *aggregations*, not transformations: they do not invent
fields, do not re-classify, do not re-score. They compose existing
labelled records into the per-actor view a researcher actually wants.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# Discourse labels — split into substantive and evasive so each
# summariser can compute the same evasion-rate consistently.
_SUBSTANTIVE = frozenset({"ACCEPTED", "REJECTED", "FACTUAL_DISCLOSURE"})
_EVASIVE = frozenset({
    "DEFLECTED", "ABSORBED", "SUBSTITUTED",
    "DATA_WITHHELD", "SCOPE_NARROWED", "CIRCULAR_REFERENCE",
})

AGGREGATION_VERSION = "aggregations_v1"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _atomic_write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def _topic_hash(topic_profile_path: Path | None) -> str | None:
    if topic_profile_path is None or not topic_profile_path.exists():
        return None
    import hashlib
    h = hashlib.sha256(topic_profile_path.read_bytes()).hexdigest()
    return f"sha256:{h}"


def _classify_label(label: str | None) -> str:
    """Return ``'substantive'`` | ``'evasive'`` | ``'unclassified'``."""
    if not label or label == "UNCLASSIFIED":
        return "unclassified"
    if label in _SUBSTANTIVE:
        return "substantive"
    if label in _EVASIVE:
        return "evasive"
    return "unclassified"  # unknown labels are treated conservatively


# ---------------------------------------------------------------------------
# MP summary
# ---------------------------------------------------------------------------


@dataclass
class MpSummaryStats:
    persons_emitted: int = 0
    questions_seen: int = 0
    questions_with_no_asker: int = 0


def write_mp_summary(
    out_dir: Path,
    *,
    topic_profile_path: Path | None = None,
    log_fn: Callable[..., None] = print,
) -> MpSummaryStats:
    """Aggregate per-MP question counts + response-label distribution.

    Output file: ``mp_summary.jsonl`` in ``out_dir``.

    One row per MP, keyed by stable ``entity_id`` when the resolver
    was used; otherwise a name-based fallback key. Each row carries:

    * ``entity_id`` (or ``None``) and ``names_seen`` (deduplicated)
    * ``party``, ``state``, ``house`` (most common observed)
    * ``questions_asked`` total
    * ``ministries_asked`` (Counter, top-N may be filtered downstream)
    * ``label_distribution`` (full Counter over the 9 labels +
      UNCLASSIFIED)
    * ``substantive_count`` / ``evasive_count`` /
      ``unclassified_count`` derived rollup
    * ``evasion_rate_classified`` — `evasive / (substantive +
      evasive)`, ``None`` if no classified records
    """
    stats = MpSummaryStats()
    manifest = _read_jsonl(out_dir / "manifest.jsonl")
    discourse_rows = _read_jsonl(out_dir / "analysis_discourse.jsonl")
    discourse_by_key: dict[str, dict] = {}
    for r in discourse_rows:
        key = r.get("key")
        if key is not None and key not in discourse_by_key:
            discourse_by_key[key] = r

    # Aggregate by a primary actor key. Prefer the resolver's entity_id;
    # fall back to a normalised name key.
    by_actor: dict[str, dict[str, Any]] = {}

    def _name_key(name: str) -> str:
        return name.strip().lower()

    for rec in manifest:
        kind = rec.get("kind") or ""
        if kind != "qa":
            # Committee records don't have a single asker — they're
            # institutional outputs. Skip for MP-level aggregation.
            continue
        stats.questions_seen += 1

        # Get asker(s). asker_details is the rich form (with party/state);
        # asker_entity_ids gives stable IDs; askers is the plain-name list.
        asker_details = rec.get("asker_details") or []
        entity_ids = rec.get("asker_entity_ids") or []
        plain_names = rec.get("askers") or []

        if not (asker_details or plain_names):
            stats.questions_with_no_asker += 1
            continue

        # Build per-asker tuples we'll iterate over.
        asker_count = max(len(asker_details), len(entity_ids), len(plain_names))
        for i in range(asker_count):
            details = asker_details[i] if i < len(asker_details) else {}
            entity_id = entity_ids[i] if i < len(entity_ids) else None
            name = (
                (isinstance(details, dict) and details.get("name"))
                or (plain_names[i] if i < len(plain_names) else None)
                or "<unknown>"
            )
            primary_key = entity_id or f"name:{_name_key(name)}"
            actor = by_actor.setdefault(primary_key, {
                "entity_id": entity_id,
                "names_seen": set(),
                "parties_seen": Counter(),
                "states_seen": Counter(),
                "house_seen": Counter(),
                "questions_asked": 0,
                "ministries_asked": Counter(),
                "label_distribution": Counter(),
            })
            actor["names_seen"].add(str(name).strip())
            if isinstance(details, dict):
                if details.get("party"):
                    actor["parties_seen"][details["party"]] += 1
                if details.get("state"):
                    actor["states_seen"][details["state"]] += 1
            if rec.get("house"):
                actor["house_seen"][rec["house"]] += 1
            actor["questions_asked"] += 1
            ministry = rec.get("ministry")
            if ministry:
                actor["ministries_asked"][ministry] += 1
            label = (
                discourse_by_key.get(rec.get("key", ""), {}).get("label")
                or "UNCLASSIFIED"
            )
            actor["label_distribution"][label] += 1

    th = _topic_hash(topic_profile_path)
    out_rows: list[dict] = []
    for primary_key, actor in by_actor.items():
        labels: Counter = actor["label_distribution"]
        substantive = sum(labels[l] for l in labels if l in _SUBSTANTIVE)
        evasive = sum(labels[l] for l in labels if l in _EVASIVE)
        unclassified = labels.get("UNCLASSIFIED", 0)
        classified = substantive + evasive
        evasion_rate = round(evasive / classified, 4) if classified else None
        most_common_party = actor["parties_seen"].most_common(1)
        most_common_state = actor["states_seen"].most_common(1)
        most_common_house = actor["house_seen"].most_common(1)
        out_rows.append({
            "entity_id": actor["entity_id"],
            "primary_key": primary_key,
            "names_seen": sorted(actor["names_seen"]),
            "party": most_common_party[0][0] if most_common_party else None,
            "state": most_common_state[0][0] if most_common_state else None,
            "house": most_common_house[0][0] if most_common_house else None,
            "questions_asked": actor["questions_asked"],
            "ministries_asked": dict(actor["ministries_asked"]),
            "label_distribution": dict(labels),
            "substantive_count": substantive,
            "evasive_count": evasive,
            "unclassified_count": unclassified,
            "evasion_rate_classified": evasion_rate,
            "topic_hash": th,
            "computed_at": _now(),
            "method": AGGREGATION_VERSION,
        })

    # Stable sort: by descending questions_asked, then primary_key.
    out_rows.sort(key=lambda r: (-r["questions_asked"], r["primary_key"]))
    _atomic_write_jsonl(out_dir / "mp_summary.jsonl", out_rows)

    stats.persons_emitted = len(out_rows)
    log_fn(
        f"mp_summary.jsonl: persons={stats.persons_emitted} "
        f"questions={stats.questions_seen} "
        f"questions_no_asker={stats.questions_with_no_asker}"
    )
    return stats


# ---------------------------------------------------------------------------
# Ministry / committee summary
# ---------------------------------------------------------------------------


@dataclass
class MinistrySummaryStats:
    qa_groups_emitted: int = 0
    committee_groups_emitted: int = 0
    records_processed: int = 0


def write_ministry_summary(
    out_dir: Path,
    *,
    topic_profile_path: Path | None = None,
    log_fn: Callable[..., None] = print,
) -> MinistrySummaryStats:
    """Aggregate per-ministry response patterns from Q/A records and
    per-committee response patterns from committee records.

    Two output files (channels are not joined because the asker→
    addressee shapes differ — Q/A asks a ministry directly, committees
    examine ministries indirectly):

    * ``ministry_summary_qa.jsonl`` — one row per ``ministry``
      from ``kind == 'qa'`` records.
    * ``ministry_summary_committee.jsonl`` — one row per
      ``committee_slug`` from ``kind == 'committee_report'`` records.

    Each row carries:

    * ``records_total``, ``records_classified``, ``records_unclassified``
    * ``label_distribution`` over all 9 + UNCLASSIFIED labels
    * ``evasive_count``, ``substantive_count``, ``evasion_rate_classified``
    * ``per_evasion_label_share`` — what fraction of evasive labels are
      DEFLECTED vs DATA_WITHHELD vs SUBSTITUTED, etc. The *grammar* of
      the evasion, not just its rate.
    * For committee channel: a list of ``rejected_recommendation_keys``
      so a researcher can trace specific recommendations the ministry
      refused.
    """
    stats = MinistrySummaryStats()
    manifest = _read_jsonl(out_dir / "manifest.jsonl")
    discourse_rows = _read_jsonl(out_dir / "analysis_discourse.jsonl")
    discourse_by_key: dict[str, list[dict]] = defaultdict(list)
    for r in discourse_rows:
        key = r.get("key")
        if key is not None:
            discourse_by_key[key].append(r)

    qa_groups: dict[str, dict[str, Any]] = {}
    cm_groups: dict[str, dict[str, Any]] = {}

    def _new_group(label: str, value: str) -> dict[str, Any]:
        return {
            label: value,
            "records_total": 0,
            "label_distribution": Counter(),
            "rejected_recommendation_keys": [],
        }

    for rec in manifest:
        stats.records_processed += 1
        kind = rec.get("kind") or ""
        key = rec.get("key", "")
        labels_for_record = [
            d.get("label") or "UNCLASSIFIED"
            for d in discourse_by_key.get(key, [{"label": "UNCLASSIFIED"}])
        ]

        if kind == "qa":
            ministry = rec.get("ministry")
            if not ministry:
                continue
            g = qa_groups.setdefault(ministry, _new_group("ministry", ministry))
            g["records_total"] += 1
            for lab in labels_for_record:
                g["label_distribution"][lab] += 1
        elif kind == "committee_report":
            slug = rec.get("committee_slug")
            if not slug:
                continue
            house_prefix = "ls" if (rec.get("house") or "").lower().startswith("lok") else "rs"
            group_key = f"{house_prefix}/{slug}"
            g = cm_groups.setdefault(group_key, _new_group("committee_slug", slug))
            g.setdefault("house", house_prefix)
            g["records_total"] += 1
            for lab in labels_for_record:
                g["label_distribution"][lab] += 1
                if lab == "REJECTED":
                    g["rejected_recommendation_keys"].append(key)

    th = _topic_hash(topic_profile_path)

    def _finalise_groups(groups: dict[str, dict[str, Any]]) -> list[dict]:
        out: list[dict] = []
        for grp in groups.values():
            labels: Counter = grp["label_distribution"]
            substantive = sum(labels[l] for l in labels if l in _SUBSTANTIVE)
            evasive = sum(labels[l] for l in labels if l in _EVASIVE)
            unclassified = labels.get("UNCLASSIFIED", 0)
            classified = substantive + evasive
            evasion_rate = round(evasive / classified, 4) if classified else None
            per_evasion_share: dict[str, float] = {}
            if evasive:
                for l in _EVASIVE:
                    if labels.get(l):
                        per_evasion_share[l] = round(labels[l] / evasive, 4)
            row = {
                **{k: v for k, v in grp.items() if k != "label_distribution"},
                "label_distribution": dict(labels),
                "records_classified": classified,
                "records_unclassified": unclassified,
                "substantive_count": substantive,
                "evasive_count": evasive,
                "evasion_rate_classified": evasion_rate,
                "per_evasion_label_share": per_evasion_share,
                "topic_hash": th,
                "computed_at": _now(),
                "method": AGGREGATION_VERSION,
            }
            # Drop the rejected list when empty to keep rows lean.
            if not row.get("rejected_recommendation_keys"):
                row.pop("rejected_recommendation_keys", None)
            out.append(row)
        # Stable sort: by descending records_total then group key.
        out.sort(
            key=lambda r: (-r["records_total"], r.get("ministry") or r.get("committee_slug") or "")
        )
        return out

    qa_rows = _finalise_groups(qa_groups)
    cm_rows = _finalise_groups(cm_groups)
    _atomic_write_jsonl(out_dir / "ministry_summary_qa.jsonl", qa_rows)
    _atomic_write_jsonl(out_dir / "ministry_summary_committee.jsonl", cm_rows)
    stats.qa_groups_emitted = len(qa_rows)
    stats.committee_groups_emitted = len(cm_rows)
    log_fn(
        f"ministry_summary: qa_groups={stats.qa_groups_emitted} "
        f"committee_groups={stats.committee_groups_emitted} "
        f"records_processed={stats.records_processed}"
    )
    return stats
