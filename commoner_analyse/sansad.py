"""Sansad questions crawler — acquisition delegated to commoner-probe.

Lok Sabha and Rajya Sabha question/answer acquisition is delegated to the
published ``commoner-probe`` package (the single source of truth). This module
used to carry a full local re-implementation as a fallback for when the probe
was absent; that fallback was dead code (``commoner-probe`` is a required
dependency that ``answers.py``/``members.py`` already import unconditionally), so
it has been removed.

What remains here is the SSC-specific semantic layer that commoner-probe does not
have:

* ``_ProbeTopicAdapter`` installs a ``record_filter_fn`` on the topic. The probe
  calls it after building each full record but before keeping it, so SSC's
  classification runs at acquisition time: it tags every record and, for Rajya
  Sabha, drops rows whose full text (title + question + answer) does not match
  the topic. Filtering here — rather than after ``append`` — keeps the probe's
  ``max_records`` and per-bucket ``no_match``/``kept`` counters aligned with the
  rows actually kept. (Requires ``commoner-probe>=0.5.1``.)
* ``append`` only aliases ``probed_at`` to ``crawled_at``; the records arrive
  already tagged and already filtered.
* ``_ClassifierRunLog`` records the classifier mode/config on each run.

The schema/key helpers (``stable_key`` etc.) are re-exported from commoner-probe
so existing ``from commoner_analyse.sansad import ...`` callers keep
working unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from commoner_probe.sansad import (  # noqa: F401  (re-export)
    SansadProbe,
    date_in_range,
    md_value,
    md_values,
    rs_date_iso,
    stable_key,
)

from ._probe_compat import ClassifierRunLog as _ClassifierRunLog
from ._probe_compat import with_crawled_at as _with_crawled_at
from .topics import TopicProfile

# Public surface: the wrapper plus the acquisition helpers/constants re-exported
# from commoner-probe so existing ``from commoner_analyse.sansad import``
# callers keep working.
__all__ = [
    "SansadCrawler",
    "SansadProbe",
    "stable_key",
    "date_in_range",
    "md_value",
    "md_values",
    "rs_date_iso",
]


class _ProbeTopicAdapter:
    """Wraps a ``TopicProfile`` for the probe.

    Nulls the probe's title-only ``filter_fn`` and installs a record-level
    ``record_filter_fn`` that applies SSC's classification over the full record
    at acquisition time.
    """

    def __init__(self, topic: TopicProfile) -> None:
        self._topic = topic
        self.filter_fn = None
        self.record_filter_fn = self._classify_and_keep

    def _classify_and_keep(self, record: dict) -> bool:
        # Called by the probe after the full record is built, before it is
        # kept. Tags every QA record in place and decides keep/drop: Rajya
        # Sabha rows are matched over title + question + answer (the answer text
        # only exists post-construction, which is why this runs here and not via
        # the probe's title-only filter_fn); Lok Sabha rows are always kept and
        # tagged by title. Non-QA records pass through untouched.
        if record.get("kind") != "qa":
            return True
        if record.get("house") == "Rajya Sabha":
            blob = " ".join(
                str(record.get(key) or "")
                for key in ("title", "question_text", "answer_text")
            )
            semantic = self._topic.classify(blob)
            if not semantic["matches"]:
                return False
        else:
            semantic = self._topic.classify(
                record.get("title"), record.get("found_via_query")
            )
        record.update(semantic)
        return True

    def __getattr__(self, name: str):
        return getattr(self._topic, name)


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
        )

    def append(self, rec: dict) -> None:
        # Records arrive already tagged and filtered by the record_filter_fn;
        # the only SSC adaptation left at write time is the crawled_at alias.
        super().append(_with_crawled_at(rec))

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
        return super().probe_rs(
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
