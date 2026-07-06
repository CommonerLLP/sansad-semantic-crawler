"""End-to-end check that SSC's RS semantic filter runs at acquisition time.

Unlike test_sansad_compat (which fakes the probe), this drives the *real*
``commoner_probe.sansad.SansadProbe`` (>=0.5.1) through ``SansadCrawler``, with
only the HTTP boundary (``rs_search_session``) and the network roster
(``_enrich_askers``) stubbed. It pins the two behaviours the append-time filter
got wrong: ``--max-records`` must cap topic-matching rows (not acquired rows),
and the per-bucket ``no_match``/``kept`` counters must reflect what was kept.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from commoner_analyse.sansad import SansadCrawler


class _LibraryTopic:
    """Minimal topic: a row matches iff its text mentions 'library'."""

    name = "library-topic"
    classifier_config = {"mode": "contract"}
    lok_sabha_ministries = ["Culture"]
    rajya_sabha_ministry_likes = ["Culture"]

    def searches(self, max_buckets: int | None = None) -> list[tuple[str, str]]:
        return [("libraries", "public library")]

    def classify(self, *parts: str | None) -> dict[str, Any]:
        blob = " ".join(str(p or "") for p in parts).lower()
        match = "library" in blob
        return {
            "tags": ["library"] if match else [],
            "matches": {"library": ["library"]} if match else {},
            "score": 1.0 if match else 0.0,
            "classifier": "contract",
        }


def _rs_row(qno: str, ans_text: str) -> dict:
    return {
        "qslno": qno,
        "ses_no": 261,
        "qtitle": f"Question {qno}",
        "ans_date": "02.01.2026",
        "qtype": "Unstarred",
        "qno": qno,
        "min_name": "Culture",
        "name": "MP One",
        "qn_text": "Question text",
        "ans_text": ans_text,
        "files": "",
        "hindifiles": "",
        "status": "Answered",
    }


def _crawler(out_dir: Path, rows: list[dict]) -> SansadCrawler:
    crawler = SansadCrawler(_LibraryTopic(), out_dir, sleep=0, classifier_mode="contract")
    crawler.rs_search_session = (
        lambda ses_no, ministry_like, member_name=None: rows
    )  # stub HTTP
    crawler._enrich_askers = lambda rec: None  # stub roster (network)
    return crawler


def _manifest(out_dir: Path) -> list[dict]:
    path = out_dir / "manifest.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _crawl_rs(crawler: SansadCrawler, seen: set[str], **kw: Any) -> int:
    return crawler.crawl_rs(
        seen,
        sessions=[261],
        from_date=None,
        to_date=None,
        qtype_filter=None,
        limit=None,
        max_buckets=None,
        max_records=kw.get("max_records"),
        download=False,
    )


def test_rs_filter_drops_nonmatches_and_tags_kept_rows(tmp_path: Path) -> None:
    rows = [
        _rs_row("1", "About roads."),               # dropped
        _rs_row("2", "The National Library grows."),  # kept
        _rs_row("3", "About bridges."),             # dropped
        _rs_row("4", "Public library funding."),    # kept
    ]
    crawler = _crawler(tmp_path, rows)
    seen: set[str] = set()
    added = _crawl_rs(crawler, seen)

    assert added == 2
    written = _manifest(tmp_path)
    assert [r["qno"] for r in written] == ["2", "4"]
    # Non-matches never entered the seen set.
    assert len(seen) == 2
    # Kept rows carry SSC's semantic tags (attached at acquisition).
    assert all(r["tags"] == ["library"] for r in written)
    assert all(r["crawled_at"] == r["probed_at"] for r in written)


def test_rs_max_records_caps_matching_rows_not_acquired_rows(tmp_path: Path) -> None:
    # First acquired row is a non-match; max_records=1 must still yield the
    # first *matching* row, not stop after acquiring the non-match.
    rows = [
        _rs_row("1", "About roads."),               # dropped
        _rs_row("2", "The National Library grows."),  # kept (the one)
        _rs_row("3", "Public library funding."),    # capped out
    ]
    crawler = _crawler(tmp_path, rows)
    seen: set[str] = set()
    added = _crawl_rs(crawler, seen, max_records=1)

    assert added == 1
    assert [r["qno"] for r in _manifest(tmp_path)] == ["2"]
