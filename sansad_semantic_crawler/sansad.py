"""Sansad questions crawler — acquisition delegated to commoner-probe.

Lok Sabha and Rajya Sabha question/answer acquisition is delegated to the
published ``commoner-probe`` package (the single source of truth). This module
used to carry a full local re-implementation as a fallback for when the probe
was absent; that fallback was dead code (``commoner-probe`` is a required
dependency that ``answers.py``/``members.py`` already import unconditionally), so
it has been removed.

What remains here is the SSC-specific semantic layer that commoner-probe does not
have:

* ``_ProbeTopicAdapter`` nulls the probe's acquisition-time ``filter_fn`` so the
  probe acquires every row, and SSC's richer append-time filter decides what to
  keep.
* ``_with_qa_semantics`` runs that append-time filter (over the full record for
  RS) and aliases ``probed_at`` to ``crawled_at``.
* ``_ClassifierRunLog`` records the classifier mode/config and corrects the
  per-run ``added`` total to the count actually written after the filter.

The schema/key helpers (``stable_key`` etc.) are re-exported from commoner-probe
so existing ``from sansad_semantic_crawler.sansad import ...`` callers keep
working unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from commoner_probe.sansad import (  # noqa: F401  (re-export)
    SansadProbe,
    date_in_range,
    md_value,
    md_values,
    rs_date_iso,
    stable_key,
)

from .topics import TopicProfile


class _ProbeTopicAdapter:
    def __init__(self, topic: TopicProfile) -> None:
        self._topic = topic
        self.filter_fn = None

    def __getattr__(self, name: str):
        return getattr(self._topic, name)


def _with_crawled_at(record: dict) -> dict:
    out = dict(record)
    if "crawled_at" not in out and out.get("probed_at"):
        out["crawled_at"] = out["probed_at"]
    return out


def _with_qa_semantics(topic: TopicProfile, record: dict) -> dict | None:
    out = _with_crawled_at(record)
    if out.get("kind") != "qa":
        return out
    if out.get("house") == "Rajya Sabha":
        blob = " ".join(
            str(out.get(key) or "")
            for key in ("title", "question_text", "answer_text")
        )
        semantic = topic.classify(blob)
        if not semantic["matches"]:
            return None
    else:
        semantic = topic.classify(out.get("title"), out.get("found_via_query"))
    out.update(semantic)
    return out


class _ClassifierRunLog:
    def __init__(
        self,
        runlog,
        *,
        classifier_mode: str,
        classifier_config: dict[str, Any],
        appended_counter=None,
    ) -> None:
        self._runlog = runlog
        self._classifier_mode = classifier_mode
        self._classifier_config = classifier_config
        # Optional callable returning the running count of records actually
        # written to the manifest. Used to correct the per-run `added` total
        # when acquisition is delegated to commoner-probe: the probe counts at
        # acquisition time, before SSC's append-time semantic filter runs.
        self._appended_counter = appended_counter
        self._appended_at_start = 0

    def start(self, **kwargs):
        kwargs.setdefault("classifier_mode", self._classifier_mode)
        kwargs.setdefault("classifier_config", self._classifier_config)
        if self._appended_counter is not None:
            self._appended_at_start = self._appended_counter()
        return self._runlog.start(**kwargs)

    def finish(self, *, added: int) -> None:
        # When delegating to commoner-probe, the probe's `added` counts rows it
        # acquired (its filter_fn is nulled by _ProbeTopicAdapter), but SSC's
        # _with_qa_semantics may drop non-matching rows at append time. Report
        # the count actually written so the run total matches the local
        # crawler's contract.
        if self._appended_counter is not None:
            added = self._appended_counter() - self._appended_at_start
        return self._runlog.finish(added=added)

    def __getattr__(self, name: str):
        return getattr(self._runlog, name)


class SansadCrawler(SansadProbe):
    """Compatibility wrapper for the commoner-probe Sansad probe."""

    def __init__(
        self,
        topic: TopicProfile,
        out_dir: Path,
        *,
        sleep: float = 0.25,
        topic_path: Path | str | None = None,
        classifier_mode: str = "regex",
        resolver=None,
    ):
        self._analysis_topic = topic
        # Bookkeeping for delegated acquisition: track how many records
        # actually survive SSC's semantic filter (_with_qa_semantics) and
        # which acquired keys were dropped, so crawl_rs can report the
        # written count and undo the probe's `seen` entries for drops.
        self._appended_count = 0
        self._dropped_keys: list[str | None] = []
        super().__init__(
            _ProbeTopicAdapter(topic),
            Path(out_dir),
            sleep=sleep,
            topic_path=topic_path,
            resolver=resolver,
        )
        self.classifier_mode = classifier_mode
        self.log_path = self.out_dir / "crawl.log"
        self.runlog = _ClassifierRunLog(
            self.runlog,
            classifier_mode=classifier_mode,
            classifier_config=topic.classifier_config,
            appended_counter=lambda: self._appended_count,
        )

    def append(self, rec: dict) -> None:
        enriched = _with_qa_semantics(self._analysis_topic, rec)
        if enriched is not None:
            super().append(enriched)
            self._appended_count += 1
        else:
            self._dropped_keys.append(rec.get("key"))

    def crawl_ls(
        self,
        seen: set[str],
        *,
        from_date: str | None,
        to_date: str | None,
        qtype_filter: str | None,
        limit: int | None,
        max_buckets: int | None,
        max_records: int | None,
        download: bool,
    ) -> int:
        return super().probe_ls(
            seen,
            from_date=from_date,
            to_date=to_date,
            qtype_filter=qtype_filter,
            limit=limit,
            max_buckets=max_buckets,
            max_records=max_records,
            download=download,
        )

    def crawl_rs(
        self,
        seen: set[str],
        *,
        sessions: Iterable[int],
        from_date: str | None,
        to_date: str | None,
        qtype_filter: str | None,
        limit: int | None,
        max_buckets: int | None,
        max_records: int | None,
        download: bool,
    ) -> int:
        # Delegate RS acquisition to commoner-probe. The probe acquires and
        # counts every row (its filter_fn is nulled by _ProbeTopicAdapter);
        # SSC's richer semantic filter runs in append() over the full
        # record (title + question + answer), dropping non-matches. Return
        # the count actually written, and undo the probe's `seen` entries
        # for dropped rows so a re-run re-evaluates them — matching the
        # local crawler's contract. (The corrected per-run total is handled
        # by _ClassifierRunLog.finish; per-bucket counters remain
        # acquisition-level.)
        before = self._appended_count
        self._dropped_keys = []
        super().probe_rs(
            seen,
            sessions=sessions,
            from_date=from_date,
            to_date=to_date,
            qtype_filter=qtype_filter,
            limit=limit,
            max_buckets=max_buckets,
            max_records=max_records,
            download=download,
        )
        for key in self._dropped_keys:
            seen.discard(key)
        return self._appended_count - before
