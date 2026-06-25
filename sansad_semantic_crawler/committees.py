"""Standing-committee report crawler — acquisition delegated to commoner-probe.

Committee report (LS/RS) and composition acquisition is delegated to the
published ``commoner-probe`` package (the single source of truth). This module
used to carry a full local re-implementation as a fallback for when the probe was
absent; that fallback was dead code (``commoner-probe`` is a required dependency
that ``answers.py``/``members.py`` already import unconditionally), so it has been
removed.

What remains here is the SSC-specific semantic layer that commoner-probe does not
have: ``_with_committee_semantics`` injects SSC's topic-classification tags at
append time and aliases ``probed_at`` to ``crawled_at``, and ``_ClassifierRunLog``
records the classifier mode/config on each run. The report-type/key helpers and
committee catalogs (``_report_type``, ``report_key``, ``resolve_committees``,
``LS_COMMITTEES`` …) are re-exported from commoner-probe so existing
``from sansad_semantic_crawler.committees import ...`` callers keep working
unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from commoner_probe.committees import (  # noqa: F401  (re-export)
    DEFAULT_LOK_SABHA,
    LS_COMMITTEES,
    REPORT_TYPE_ACTION_TAKEN,
    REPORT_TYPE_BILL,
    REPORT_TYPE_DFG,
    REPORT_TYPE_OTHER,
    REPORT_TYPE_SUBJECT,
    REPORT_TYPES_KNOWN,
    RS_COMMITTEES,
    CommitteeProbe,
    _ls_presented_via,
    _report_type,
    parse_ls_date,
    parse_rs_date,
    report_key,
    resolve_committees,
)

from .topics import TopicProfile


def _with_crawled_at(record: dict) -> dict:
    out = dict(record)
    if "crawled_at" not in out and out.get("probed_at"):
        out["crawled_at"] = out["probed_at"]
    return out


def _with_committee_semantics(topic: TopicProfile, record: dict) -> dict:
    out = _with_crawled_at(record)
    if out.get("kind") == "committee_report":
        out.update(topic.classify(out.get("title")))
    return out


class _ClassifierRunLog:
    def __init__(
        self,
        runlog,
        *,
        classifier_mode: str,
        classifier_config: dict[str, Any],
    ) -> None:
        self._runlog = runlog
        self._classifier_mode = classifier_mode
        self._classifier_config = classifier_config

    def start(self, **kwargs):
        kwargs.setdefault("classifier_mode", self._classifier_mode)
        kwargs.setdefault("classifier_config", self._classifier_config)
        return self._runlog.start(**kwargs)

    def __getattr__(self, name: str):
        return getattr(self._runlog, name)


class CommitteeCrawler(CommitteeProbe):
    """Compatibility wrapper for the commoner-probe committee probe."""

    def __init__(
        self,
        topic: TopicProfile,
        out_dir: Path,
        *,
        sleep: float = 0.25,
        lok_sabha_no: int = DEFAULT_LOK_SABHA,
        topic_path: Path | str | None = None,
        classifier_mode: str = "regex",
    ) -> None:
        super().__init__(
            topic,
            Path(out_dir),
            sleep=sleep,
            lok_sabha_no=lok_sabha_no,
            topic_path=topic_path,
        )
        self.classifier_mode = classifier_mode
        self.log_path = self.out_dir / "crawl.log"
        self.composition_manifest = self.out_dir / "committee_members.jsonl"
        self.runlog = _ClassifierRunLog(
            self.runlog,
            classifier_mode=classifier_mode,
            classifier_config=self.topic.classifier_config,
        )

    def append(self, rec: dict) -> None:
        super().append(_with_committee_semantics(self.topic, rec))

    def crawl_ls(
        self,
        seen: set[str],
        *,
        committees: list[str],
        from_date: str | None,
        to_date: str | None,
        max_records: int | None,
        download: bool,
    ) -> int:
        return super().probe_ls(
            seen,
            committees=committees,
            from_date=from_date,
            to_date=to_date,
            max_records=max_records,
            download=download,
        )

    def crawl_rs(
        self,
        seen: set[str],
        *,
        committees: list[str],
        from_date: str | None,
        to_date: str | None,
        max_records: int | None,
        download: bool,
    ) -> int:
        return super().probe_rs(
            seen,
            committees=committees,
            from_date=from_date,
            to_date=to_date,
            max_records=max_records,
            download=download,
        )

    def crawl_composition(self, house: str, committees: Iterable[str]) -> int:
        added = super().probe_composition(house, committees)
        self._patch_composition_crawled_at()
        return added

    def _patch_composition_crawled_at(self) -> None:
        path = self.composition_manifest
        if not path.exists():
            return
        records = []
        changed = False
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                patched = _with_crawled_at(rec)
                changed = changed or patched != rec
                records.append(patched)
        if not changed:
            return
        with path.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
