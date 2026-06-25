from __future__ import annotations

import importlib
import json
import sys
import types
import unittest.mock as mock
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any


REAL_IMPORT_MODULE = importlib.import_module
TARGET_MODULE = "sansad_semantic_crawler.sansad"


@contextmanager
def reloaded_sansad(probe_class: type) -> Iterator[ModuleType]:
    """Reload the SSC sansad module with the commoner-probe SansadProbe patched.

    Acquisition is delegated to ``commoner_probe.sansad.SansadProbe`` (a hard
    dependency). We patch that class to a fake before re-importing the SSC module
    so ``SansadCrawler`` subclasses the fake; the re-exported helpers continue to
    resolve from the real ``commoner_probe.sansad`` module.
    """
    original = sys.modules.pop(TARGET_MODULE, None)
    package = sys.modules.get("sansad_semantic_crawler")
    old_attr = getattr(package, "sansad", None) if package is not None else None
    if package is not None and hasattr(package, "sansad"):
        delattr(package, "sansad")
    try:
        with mock.patch("commoner_probe.sansad.SansadProbe", probe_class):
            yield REAL_IMPORT_MODULE(TARGET_MODULE)
    finally:
        sys.modules.pop(TARGET_MODULE, None)
        if original is not None:
            sys.modules[TARGET_MODULE] = original
        if package is not None and old_attr is not None:
            setattr(package, "sansad", old_attr)


class ContractTopic:
    name = "contract-libraries"
    classifier_config = {"mode": "contract-regex"}
    lok_sabha_ministries = ["Culture"]
    rajya_sabha_ministry_likes = ["Culture"]

    def searches(self, max_buckets: int | None = None) -> list[tuple[str, str]]:
        searches = [("libraries", "public library")]
        return searches[:max_buckets] if max_buckets is not None else searches

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


class NoMatchTopic(ContractTopic):
    def classify(self, *_parts: str | None) -> dict[str, Any]:
        return {
            "tags": [],
            "matches": {},
            "score": 0.0,
            "classifier": "contract-regex",
        }


class FakeRunLog:
    def __init__(self) -> None:
        self.start_kwargs: dict[str, Any] | None = None
        self.finished_added: int | None = None
        self.buckets: list[dict[str, Any]] = []

    def start(self, **kwargs: Any) -> str:
        self.start_kwargs = kwargs
        return "fake-run-id"

    def record_bucket(self, **kwargs: Any) -> None:
        self.buckets.append(kwargs)

    def record_error(self, **_kwargs: Any) -> None:
        pass

    def finish(self, *, added: int) -> None:
        self.finished_added = added


class FakeSansadProbe:
    def __init__(
        self,
        topic,
        out_dir: Path,
        *,
        sleep: float = 0.25,
        topic_path: Path | str | None = None,
        resolver=None,
    ) -> None:
        self.topic = topic
        self.out_dir = Path(out_dir)
        self.pdf_dir = self.out_dir / "pdfs"
        self.manifest = self.out_dir / "manifest.jsonl"
        self.log_path = self.out_dir / "probe.log"
        self.sleep = sleep
        self.topic_path = topic_path
        self.resolver = resolver
        self.runlog = FakeRunLog()
        self.session = types.SimpleNamespace(headers={})

    def append(self, rec: dict) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        with self.manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def log(self, _message: str) -> None:
        pass

    def load_seen(self) -> set[str]:
        return set()

    def _enrich_askers(self, rec: dict) -> None:
        rec.setdefault(
            "asker_details",
            [{"name": name, "party": None} for name in rec.get("askers", [])],
        )
        rec.setdefault("asker_entity_ids", [None for _name in rec.get("askers", [])])
        rec.setdefault("responder_entity_id", None)
        rec.setdefault("responder_role_at_event", None)

    def rs_search_session(self, ses_no: int, ministry_like: str) -> list[dict]:
        return [
            {
                "qslno": "99",
                "ses_no": ses_no,
                "qtitle": "National Mission on Libraries",
                "ans_date": "02.01.2026",
                "qtype": "Unstarred",
                "qno": "43",
                "min_name": f"{ministry_like} and Culture",
                "name": "MP Two",
                "qn_text": "Will the Minister state public library plans?",
                "ans_text": "The National Mission on Libraries supports public libraries.",
                "files": "https://rsdoc.nic.in/q/43.pdf",
                "hindifiles": "https://rsdoc.nic.in/q/43-h.pdf",
                "status": "Answered",
            }
        ]

    def probe_ls(self, seen: set[str], **_kwargs: Any) -> int:
        assert self.topic.filter_fn is None
        self.runlog.start(
            kind="qa",
            scope={"house": "ls"},
            topic_name=self.topic.name,
            topic_path=self.topic_path,
            classifier_config=self.topic.classifier_config,
        )
        rec = {
            "key": "LS|U|42|2026-01-01",
            "run_id": "fake-run-id",
            "kind": "qa",
            "house": "Lok Sabha",
            "uuid": "uuid-42",
            "handle": "123456789/42",
            "title": "National Mission on Libraries and public libraries",
            "date": "2026-01-01",
            "qtype": "Unstarred",
            "qno": "42",
            "session": "18",
            "loksabhanumber": "18",
            "ministry": "Culture",
            "askers": ["MP One"],
            "asker_details": [{"name": "MP One", "party": None}],
            "asker_entity_ids": [None],
            "responder_entity_id": None,
            "responder_role_at_event": None,
            "uri": "https://eparlib.nic.in/handle/123456789/42",
            "source": "elibrary.sansad.in",
            "found_via_group": "libraries",
            "found_via_query": "public library",
            "language_classified": ["en"],
            "probed_at": "2026-06-02T12:00:00",
        }
        self.append(rec)
        seen.add(rec["key"])
        self.runlog.finish(added=1)
        return 1

    def probe_rs(self, seen: set[str], **_kwargs: Any) -> int:
        assert self.topic.filter_fn is None
        self.runlog.start(
            kind="qa",
            scope={"house": "rs"},
            topic_name=self.topic.name,
            topic_path=self.topic_path,
            classifier_config=self.topic.classifier_config,
        )
        rec = {
            "key": "RS|U|43|2026-01-02",
            "run_id": "fake-run-id",
            "kind": "qa",
            "house": "Rajya Sabha",
            "qslno": "99",
            "ses_no": 261,
            "title": "National Mission on Libraries",
            "date": "2026-01-02",
            "qtype": "Unstarred",
            "qno": "43",
            "ministry": "Culture",
            "askers": ["MP Two"],
            "asker_details": [{"name": "MP Two", "party": None}],
            "asker_entity_ids": [None],
            "responder_entity_id": None,
            "responder_role_at_event": None,
            "question_text": "Will the Minister state public library plans?",
            "answer_text": "The National Mission on Libraries supports public libraries.",
            "pdf_url": "https://rsdoc.nic.in/q/43.pdf",
            "pdf_url_hindi": "https://rsdoc.nic.in/q/43-h.pdf",
            "source": "rsdoc.nic.in",
            "found_via_query": "Culture",
            "status": "Answered",
            "language_classified": ["en"],
            "probed_at": "2026-06-02T12:01:00",
        }
        self.append(rec)
        seen.add(rec["key"])
        # Mirror the real probe_rs: with filter_fn nulled by the adapter the
        # probe records buckets at acquisition time (no_match=0, kept=acquired)
        # and finishes with the acquired count. SSC's wrapper corrects the
        # written total downstream.
        self.runlog.record_bucket(
            kind="rs_qa",
            session=261,
            ministry="Culture",
            raw_returned=1,
            after_date_filter=1,
            no_match=0,
            kept=1,
            skipped_seen=0,
        )
        self.runlog.finish(added=1)
        return 1


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_sansad_delegates_to_commoner_probe_when_available(tmp_path: Path) -> None:
    with reloaded_sansad(FakeSansadProbe) as sansad:
        crawler = sansad.SansadCrawler(
            ContractTopic(),
            tmp_path,
            sleep=0,
            topic_path=Path("topic.json"),
            classifier_mode="contract-regex",
        )

        assert isinstance(crawler, FakeSansadProbe)
        assert crawler.log_path == tmp_path / "crawl.log"
        assert crawler.topic.filter_fn is None


def test_delegated_sansad_ls_keeps_local_semantic_contract(tmp_path: Path) -> None:
    with reloaded_sansad(FakeSansadProbe) as sansad:
        crawler = sansad.SansadCrawler(
            ContractTopic(),
            tmp_path,
            sleep=0,
            topic_path=Path("topic.json"),
            classifier_mode="contract-regex",
        )
        added = crawler.crawl_ls(
            set(),
            from_date=None,
            to_date=None,
            qtype_filter=None,
            limit=None,
            max_buckets=1,
            max_records=1,
            download=False,
        )

        assert added == 1
        assert crawler.runlog.start_kwargs["classifier_mode"] == "contract-regex"
        assert crawler.runlog.start_kwargs["classifier_config"] == {"mode": "contract-regex"}

    row = _read_jsonl(tmp_path / "manifest.jsonl")[0]
    assert row["house"] == "Lok Sabha"
    assert row["found_via_group"] == "libraries"
    assert row["found_via_query"] == "public library"
    assert row["probed_at"] == "2026-06-02T12:00:00"
    assert row["crawled_at"] == "2026-06-02T12:00:00"
    assert row["tags"] == ["nml", "public_library"]
    assert row["matches"] == {
        "nml": ["National Mission on Libraries"],
        "public_library": ["public library"],
    }
    assert row["score"] == 2.0
    assert row["classifier"] == "contract-regex"


def test_sansad_rs_delegates_and_keeps_semantic_contract_when_commoner_probe_available(
    tmp_path: Path,
) -> None:
    with reloaded_sansad(FakeSansadProbe) as sansad:
        crawler = sansad.SansadCrawler(
            ContractTopic(),
            tmp_path,
            sleep=0,
            topic_path=Path("topic.json"),
            classifier_mode="contract-regex",
        )
        added = crawler.crawl_rs(
            set(),
            sessions=[261],
            from_date=None,
            to_date=None,
            qtype_filter=None,
            limit=None,
            max_buckets=1,
            max_records=1,
            download=False,
        )

        assert added == 1
        assert crawler.runlog.start_kwargs["classifier_mode"] == "contract-regex"

    row = _read_jsonl(tmp_path / "manifest.jsonl")[0]
    assert row["house"] == "Rajya Sabha"
    assert row["question_text"] == "Will the Minister state public library plans?"
    assert row["answer_text"] == (
        "The National Mission on Libraries supports public libraries."
    )
    assert row["found_via_query"] == "Culture"
    # RS delegates to commoner-probe (symmetric with LS): the probe's
    # `probed_at` is preserved and aliased to `crawled_at`.
    assert row["probed_at"] == "2026-06-02T12:01:00"
    assert row["crawled_at"] == "2026-06-02T12:01:00"
    assert row["tags"] == ["nml", "public_library"]
    assert row["classifier"] == "contract-regex"


def test_sansad_rs_no_match_dropped_by_semantic_filter_when_commoner_probe_available(
    tmp_path: Path,
) -> None:
    with reloaded_sansad(FakeSansadProbe) as sansad:
        crawler = sansad.SansadCrawler(
            NoMatchTopic(),
            tmp_path,
            sleep=0,
            topic_path=Path("topic.json"),
            classifier_mode="contract-regex",
        )
        seen: set[str] = set()
        added = crawler.crawl_rs(
            seen,
            sessions=[261],
            from_date=None,
            to_date=None,
            qtype_filter=None,
            limit=None,
            max_buckets=1,
            max_records=1,
            download=False,
        )

        # The semantic filter drops the non-matching row: nothing is written,
        # the returned count and corrected run total are both 0, and the
        # wrapper undoes the probe's `seen` entry so a re-run re-evaluates it.
        assert added == 0
        assert seen == set()
        assert not (tmp_path / "manifest.jsonl").exists()
        assert crawler.runlog.finished_added == 0
        # The probe records buckets at acquisition time (before SSC's
        # append-time filter), so the per-bucket counters show the row as
        # acquired/kept; the semantic drop is reflected only in the corrected
        # run total above and the empty manifest, not the per-bucket numbers.
        assert crawler.runlog.buckets[-1]["no_match"] == 0
        assert crawler.runlog.buckets[-1]["kept"] == 1
