from __future__ import annotations

import importlib
import sys
import types
import unittest.mock as mock
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType


REAL_IMPORT_MODULE = importlib.import_module
TARGET_MODULE = "sansad_semantic_crawler.neva"


@contextmanager
def reloaded_neva(probe_class: type) -> Iterator[ModuleType]:
    """Reload the SSC neva module with the commoner-probe crawler patched.

    Acquisition is delegated to ``commoner_probe.neva.StateAssemblyCrawler`` (a
    hard dependency). We patch that class to a fake before re-importing the SSC
    module so ``NevaStateCrawler`` subclasses the fake.
    """
    original = sys.modules.pop(TARGET_MODULE, None)
    package = sys.modules.get("sansad_semantic_crawler")
    old_attr = getattr(package, "neva", None) if package is not None else None
    if package is not None and hasattr(package, "neva"):
        delattr(package, "neva")
    try:
        with mock.patch("commoner_probe.neva.StateAssemblyCrawler", probe_class):
            yield REAL_IMPORT_MODULE(TARGET_MODULE)
    finally:
        sys.modules.pop(TARGET_MODULE, None)
        if original is not None:
            sys.modules[TARGET_MODULE] = original
        if package is not None and old_attr is not None:
            setattr(package, "neva", old_attr)


class FakeStateAssemblyCrawler:
    def __init__(
        self,
        portal_code: str,
        state_code: str,
        out_dir: Path,
        *,
        sleep: float = 0.5,
    ) -> None:
        self.portal_code = portal_code
        self.state_code = state_code
        self.out_dir = Path(out_dir)
        self.sleep = sleep
        self.log_path = self.out_dir / "probe.log"
        self.session = types.SimpleNamespace(headers={})
        self.questions_path = self.out_dir / "questions.jsonl"
        self.unlisted_path = self.out_dir / "questions_unlisted.jsonl"
        self.members_path = self.out_dir / "members.jsonl"
        self.papers_path = self.out_dir / "papers_laid.jsonl"

    def fetch_questions_for_date(self, *_args, **_kwargs):
        return [{"key": "GJ|q|15|1|101|42", "probed_at": "2026-06-01T00:00:00"}]

    def fetch_unlisted_questions(self, *_args, **_kwargs):
        return [{"key": "GJ|q_unlist|15|1|43", "probed_at": "2026-06-01T00:01:00"}]

    def fetch_members(self, *_args, **_kwargs):
        return [{"key": "GJ|member|101", "probed_at": "2026-06-01T00:02:00"}]

    def fetch_papers_laid(self, *_args, **_kwargs):
        return [{"key": "GJ|paper|15|1|101|0", "probed_at": "2026-06-01T00:03:00"}]


def test_neva_delegates_to_commoner_probe(tmp_path):
    with reloaded_neva(FakeStateAssemblyCrawler) as neva:
        crawler = neva.NevaStateCrawler("gujarat", "GJ", tmp_path, sleep=0)

        assert isinstance(crawler, FakeStateAssemblyCrawler)
        assert crawler.log_path == tmp_path / "crawl.log"
        assert crawler.session.headers["User-Agent"] == neva.NEVA_UA


def test_delegated_neva_records_keep_crawled_at_compatibility(tmp_path):
    with reloaded_neva(FakeStateAssemblyCrawler) as neva:
        crawler = neva.NevaStateCrawler("gujarat", "GJ", tmp_path, sleep=0)
        rows = [
            crawler.fetch_questions_for_date(15, 1, 101, set())[0],
            crawler.fetch_unlisted_questions(15, 1, set())[0],
            crawler.fetch_members(15)[0],
            crawler.fetch_papers_laid(15, 1, 101, set())[0],
        ]

    assert [row["crawled_at"] for row in rows] == [
        "2026-06-01T00:00:00",
        "2026-06-01T00:01:00",
        "2026-06-01T00:02:00",
        "2026-06-01T00:03:00",
    ]
    assert all("probed_at" in row for row in rows)
