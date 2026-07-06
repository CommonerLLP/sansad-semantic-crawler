"""NeVA (National e-Vidhan Application) state assembly crawler — acquisition
delegated to commoner-probe.

State-assembly acquisition (questions, unlisted questions, members, papers to
be laid) is delegated to the published ``commoner-probe`` package (the single
source of truth — ``commoner_probe.neva.StateAssemblyCrawler``). This module
used to carry a full local re-implementation as a fallback for when the probe
was absent; that fallback was dead code (``commoner-probe`` is a required
dependency that ``sansad.py``/``committees.py`` already import
unconditionally), so it has been removed.

What remains here is a thin compatibility wrapper: ``NevaStateCrawler``
subclasses the probe's crawler, points its log file at ``crawl.log`` (the SSC
convention), sets SSC's own User-Agent string, and aliases the probe's
``probed_at`` field to ``crawled_at`` on every record for backward
compatibility with consumers of the old local crawler's output.
"""
from __future__ import annotations

from pathlib import Path

from commoner_probe.neva import StateAssemblyCrawler

from ._probe_compat import with_crawled_at as _with_crawled_at

NEVA_UA = "commoner-analyse/2.1.0 (research)"


def _with_crawled_at_rows(records: list[dict]) -> list[dict]:
    return [_with_crawled_at(record) for record in records]


class NevaStateCrawler(StateAssemblyCrawler):
    """Compatibility wrapper for the commoner-probe NeVA crawler."""

    def __init__(
        self,
        portal_code: str,
        state_code: str,
        out_dir: Path,
        *,
        sleep: float = 0.5,
    ) -> None:
        super().__init__(portal_code, state_code, Path(out_dir), sleep=sleep)
        self.log_path = self.out_dir / "crawl.log"
        self.session.headers.update({"User-Agent": NEVA_UA})

    def fetch_questions_for_date(
        self,
        assembly_no: int,
        session_code: int,
        date_id: int,
        seen: set[str],
    ) -> list[dict]:
        return _with_crawled_at_rows(
            super().fetch_questions_for_date(
                assembly_no,
                session_code,
                date_id,
                seen,
            )
        )

    def fetch_unlisted_questions(
        self,
        assembly_no: int,
        session_code: int,
        seen: set[str],
    ) -> list[dict]:
        return _with_crawled_at_rows(
            super().fetch_unlisted_questions(assembly_no, session_code, seen)
        )

    def fetch_members(self, assembly_no: int) -> list[dict]:
        return _with_crawled_at_rows(super().fetch_members(assembly_no))

    def fetch_papers_laid(
        self,
        assembly_no: int,
        session_code: int,
        date_id: int,
        seen: set[str],
    ) -> list[dict]:
        return _with_crawled_at_rows(
            super().fetch_papers_laid(
                assembly_no,
                session_code,
                date_id,
                seen,
            )
        )
