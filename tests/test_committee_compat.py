from __future__ import annotations

import importlib
import json
import sys
import types
import unittest.mock as mock
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


REAL_IMPORT_MODULE = importlib.import_module
TARGET_MODULE = "sansad_semantic_crawler.committees"


@contextmanager
def reloaded_committees(import_module: Callable[[str], ModuleType]) -> Iterator[ModuleType]:
    original = sys.modules.pop(TARGET_MODULE, None)
    package = sys.modules.get("sansad_semantic_crawler")
    old_attr = getattr(package, "committees", None) if package is not None else None
    if package is not None and hasattr(package, "committees"):
        delattr(package, "committees")
    try:
        with mock.patch("importlib.import_module", side_effect=import_module):
            yield REAL_IMPORT_MODULE(TARGET_MODULE)
    finally:
        sys.modules.pop(TARGET_MODULE, None)
        if original is not None:
            sys.modules[TARGET_MODULE] = original
        if package is not None and old_attr is not None:
            setattr(package, "committees", old_attr)


class ContractTopic:
    name = "contract-libraries"
    classifier_config = {"mode": "contract-regex"}

    def classify(self, *_parts: str | None) -> dict[str, Any]:
        return {
            "tags": ["nml", "public_library"],
            "matches": {
                "nml": ["National Mission on Libraries"],
                "public_library": ["public library"],
            },
            "score": 2.0,
            "classifier": "contract-regex",
        }


class FakeRunLog:
    def __init__(self) -> None:
        self.start_kwargs: dict[str, Any] | None = None
        self.finished_added: int | None = None

    def start(self, **kwargs: Any) -> str:
        self.start_kwargs = kwargs
        return "fake-run-id"

    def record_error(self, **_kwargs: Any) -> None:
        pass

    def finish(self, *, added: int) -> None:
        self.finished_added = added


class FakeCommitteeProbe:
    def __init__(
        self,
        topic: ContractTopic,
        out_dir: Path,
        *,
        sleep: float = 0.25,
        lok_sabha_no: int = 18,
        topic_path: Path | str | None = None,
    ) -> None:
        self.topic = topic
        self.out_dir = Path(out_dir)
        self.pdf_dir = self.out_dir / "pdfs"
        self.manifest = self.out_dir / "manifest.jsonl"
        self.log_path = self.out_dir / "probe.log"
        self.sleep = sleep
        self.lok_sabha_no = lok_sabha_no
        self.topic_path = topic_path
        self.runlog = FakeRunLog()
        self.session = types.SimpleNamespace(headers={})

    def append(self, rec: dict) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        with self.manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def probe_ls(self, seen: set[str], **_kwargs: Any) -> int:
        self.runlog.start(
            kind="committee_report",
            scope={"house": "ls"},
            topic_name=self.topic.name,
            topic_path=self.topic_path,
        )
        rec = {
            "key": "LS|finance|35|18",
            "run_id": "fake-run-id",
            "house": "Lok Sabha",
            "kind": "committee_report",
            "report_type": "demands_for_grants",
            "presented_via": "both_houses",
            "committee_slug": "finance",
            "committee_name": "Finance",
            "report_no": 35,
            "loksabha_no": self.lok_sabha_no,
            "title": "Demands for Grants and National Mission on Libraries",
            "language_classified": ["en"],
            "date": "2026-03-17",
            "source": "sansad.in/api_ls/committee",
            "probed_at": "2026-06-02T12:01:00",
        }
        self.append(rec)
        seen.add(rec["key"])
        self.runlog.finish(added=1)
        return 1

    def probe_rs(self, seen: set[str], **_kwargs: Any) -> int:
        rec = {
            "key": "RS|health|174",
            "run_id": "fake-run-id",
            "house": "Rajya Sabha",
            "kind": "committee_report",
            "report_type": "subject",
            "presented_via": "rs_only",
            "committee_slug": "health",
            "committee_name": "Health and Family Welfare",
            "report_no": 174,
            "title": "Review of public libraries in hospitals",
            "language_classified": ["en"],
            "date": "2026-03-18",
            "source": "sansad.in/api_rs/committee",
            "probed_at": "2026-06-02T12:02:00",
        }
        self.append(rec)
        seen.add(rec["key"])
        return 1

    def probe_composition(self, _house: str, _committees: list[str]) -> int:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "house": "LS",
            "committee": "finance",
            "committee_name": "Finance",
            "committee_code": 12,
            "source": "api",
            "members": [{"name": "Member One", "role": "Member"}],
            "probed_at": "2026-06-02T12:03:00",
        }
        with (self.out_dir / "committee_members.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return 1


def _fake_commoner_committees_module() -> ModuleType:
    module = types.ModuleType("commoner_probe.committees")
    module.CommitteeProbe = FakeCommitteeProbe
    return module


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_committees_delegate_to_commoner_probe_when_available(tmp_path: Path) -> None:
    def fake_import_module(name: str) -> ModuleType:
        if name == "commoner_probe.committees":
            return _fake_commoner_committees_module()
        return REAL_IMPORT_MODULE(name)

    with reloaded_committees(fake_import_module) as committees:
        crawler = committees.CommitteeCrawler(
            ContractTopic(),
            tmp_path,
            sleep=0,
            lok_sabha_no=18,
            topic_path=Path("topic.json"),
            classifier_mode="contract-regex",
        )

        assert committees.USING_COMMONER_PROBE_COMMITTEES is True
        assert isinstance(crawler, FakeCommitteeProbe)
        assert crawler.log_path == tmp_path / "crawl.log"
        assert crawler.composition_manifest == tmp_path / "committee_members.jsonl"


def test_delegated_committee_reports_keep_local_semantic_contract(
    tmp_path: Path,
) -> None:
    def fake_import_module(name: str) -> ModuleType:
        if name == "commoner_probe.committees":
            return _fake_commoner_committees_module()
        return REAL_IMPORT_MODULE(name)

    with reloaded_committees(fake_import_module) as committees:
        crawler = committees.CommitteeCrawler(
            ContractTopic(),
            tmp_path,
            sleep=0,
            lok_sabha_no=18,
            topic_path=Path("topic.json"),
            classifier_mode="contract-regex",
        )
        added = crawler.crawl_ls(
            set(),
            committees=["finance"],
            from_date=None,
            to_date=None,
            max_records=None,
            download=False,
        )

        assert added == 1
        assert crawler.runlog.start_kwargs["classifier_mode"] == "contract-regex"
        assert crawler.runlog.start_kwargs["classifier_config"] == {"mode": "contract-regex"}

    row = _read_jsonl(tmp_path / "manifest.jsonl")[0]
    assert row["report_type"] == "demands_for_grants"
    assert row["committee_slug"] == "finance"
    assert row["presented_via"] == "both_houses"
    assert row["probed_at"] == "2026-06-02T12:01:00"
    assert row["crawled_at"] == "2026-06-02T12:01:00"
    assert row["tags"] == ["nml", "public_library"]
    assert row["matches"] == {
        "nml": ["National Mission on Libraries"],
        "public_library": ["public library"],
    }
    assert row["score"] == 2.0
    assert row["classifier"] == "contract-regex"


def test_delegated_committee_composition_keeps_crawled_at_compatibility(
    tmp_path: Path,
) -> None:
    def fake_import_module(name: str) -> ModuleType:
        if name == "commoner_probe.committees":
            return _fake_commoner_committees_module()
        return REAL_IMPORT_MODULE(name)

    with reloaded_committees(fake_import_module) as committees:
        crawler = committees.CommitteeCrawler(
            ContractTopic(),
            tmp_path,
            sleep=0,
            topic_path=Path("topic.json"),
            classifier_mode="contract-regex",
        )
        assert crawler.crawl_composition("ls", ["finance"]) == 1

    row = _read_jsonl(tmp_path / "committee_members.jsonl")[0]
    assert row["probed_at"] == "2026-06-02T12:03:00"
    assert row["crawled_at"] == "2026-06-02T12:03:00"


def test_committees_fall_back_to_local_crawler_when_commoner_probe_is_absent(
    tmp_path: Path,
) -> None:
    def fake_import_module(name: str) -> ModuleType:
        if name == "commoner_probe.committees":
            raise ModuleNotFoundError(name, name="commoner_probe")
        return REAL_IMPORT_MODULE(name)

    with reloaded_committees(fake_import_module) as committees:
        crawler = committees.CommitteeCrawler(
            ContractTopic(),
            tmp_path,
            sleep=0,
            classifier_mode="contract-regex",
        )

        assert committees.USING_COMMONER_PROBE_COMMITTEES is False
        assert crawler.log_path == tmp_path / "crawl.log"
        assert crawler.composition_manifest == tmp_path / "committee_members.jsonl"
        assert hasattr(crawler, "crawl_ls")


def test_commoner_probe_internal_import_errors_are_not_silently_hidden() -> None:
    def fake_import_module(name: str) -> ModuleType:
        if name == "commoner_probe.committees":
            raise ModuleNotFoundError(
                "No module named 'missing_dependency'",
                name="missing_dependency",
            )
        return REAL_IMPORT_MODULE(name)

    with pytest.raises(ModuleNotFoundError):
        with reloaded_committees(fake_import_module):
            pass
