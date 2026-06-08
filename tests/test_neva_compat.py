from __future__ import annotations

import importlib
import sys
import types
import unittest.mock as mock
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest


REAL_IMPORT_MODULE = importlib.import_module
TARGET_MODULE = "sansad_semantic_crawler.neva"


@contextmanager
def reloaded_neva(import_module: Callable[[str], ModuleType]) -> Iterator[ModuleType]:
    original = sys.modules.pop(TARGET_MODULE, None)
    package = sys.modules.get("sansad_semantic_crawler")
    old_attr = getattr(package, "neva", None) if package is not None else None
    if package is not None and hasattr(package, "neva"):
        delattr(package, "neva")
    try:
        with mock.patch("importlib.import_module", side_effect=import_module):
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


def _fake_commoner_neva_module() -> ModuleType:
    module = types.ModuleType("commoner_probe.neva")
    module.StateAssemblyCrawler = FakeStateAssemblyCrawler
    return module


def test_neva_delegates_to_commoner_probe_when_available(tmp_path):
    def fake_import_module(name: str) -> ModuleType:
        if name == "commoner_probe.neva":
            return _fake_commoner_neva_module()
        return REAL_IMPORT_MODULE(name)

    with reloaded_neva(fake_import_module) as neva:
        crawler = neva.NevaStateCrawler("gujarat", "GJ", tmp_path, sleep=0)

        assert neva.USING_COMMONER_PROBE_NEVA is True
        assert isinstance(crawler, FakeStateAssemblyCrawler)
        assert crawler.log_path == tmp_path / "crawl.log"
        assert crawler.session.headers["User-Agent"] == neva.NEVA_UA


def test_delegated_neva_records_keep_crawled_at_compatibility(tmp_path):
    def fake_import_module(name: str) -> ModuleType:
        if name == "commoner_probe.neva":
            return _fake_commoner_neva_module()
        return REAL_IMPORT_MODULE(name)

    with reloaded_neva(fake_import_module) as neva:
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


def test_neva_falls_back_to_local_crawler_when_commoner_probe_is_absent(tmp_path):
    def fake_import_module(name: str) -> ModuleType:
        if name == "commoner_probe.neva":
            raise ModuleNotFoundError(name, name="commoner_probe")
        return REAL_IMPORT_MODULE(name)

    with reloaded_neva(fake_import_module) as neva:
        crawler = neva.NevaStateCrawler("gujarat", "GJ", tmp_path, sleep=0)

        assert neva.USING_COMMONER_PROBE_NEVA is False
        assert crawler.log_path == tmp_path / "crawl.log"
        assert crawler.questions_path == tmp_path / "questions.jsonl"
        assert crawler.papers_path == tmp_path / "papers_laid.jsonl"


def test_commoner_probe_internal_import_errors_are_not_silently_hidden():
    def fake_import_module(name: str) -> ModuleType:
        if name == "commoner_probe.neva":
            raise ModuleNotFoundError(
                "No module named 'missing_dependency'",
                name="missing_dependency",
            )
        return REAL_IMPORT_MODULE(name)

    with pytest.raises(ModuleNotFoundError):
        with reloaded_neva(fake_import_module):
            pass
