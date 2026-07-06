from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any


def acquisition_log_for(out_dir: Path) -> str | None:
    if (out_dir / "probe.log").exists():
        return "probe.log"
    if (out_dir / "crawl.log").exists():
        return "crawl.log"
    return None


def acquisition_source_for(record: Mapping[str, Any]) -> str:
    if record.get("probed_at"):
        return "commoner-probe"
    if record.get("crawled_at"):
        return "commoner-analyse"
    return "unknown"


def acquired_at_for(record: Mapping[str, Any]) -> str:
    return str(record.get("probed_at") or record.get("crawled_at") or "")


def normalize_manifest_record(
    record: Mapping[str, Any],
    *,
    acquisition_log: str | None = None,
) -> dict[str, Any]:
    normalized = dict(record)

    tags = normalized.get("tags")
    if tags is None:
        normalized["tags"] = []
    elif not isinstance(tags, list):
        normalized["tags"] = [tags]

    matches = normalized.get("matches")
    if not isinstance(matches, dict):
        normalized["matches"] = {}

    normalized.setdefault("score", 0)
    normalized["classifier"] = normalized.get("classifier") or ""
    normalized.setdefault("acquisition_source", acquisition_source_for(normalized))
    normalized.setdefault("acquired_at", acquired_at_for(normalized))
    if acquisition_log is not None:
        normalized.setdefault("acquisition_log", acquisition_log)
    return normalized


def iter_manifest_records(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    acquisition_log = acquisition_log_for(path.parent)
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            yield normalize_manifest_record(record, acquisition_log=acquisition_log)
