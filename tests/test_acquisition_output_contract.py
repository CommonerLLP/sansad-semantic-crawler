from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from commoner_analyse.committees import CommitteeCrawler
from commoner_analyse.manifest_contract import iter_manifest_records
from commoner_analyse.sansad import SansadCrawler
from commoner_analyse.textparse import parse_corpus


ROOT = Path(__file__).resolve().parents[1]
TOPIC_PATH = ROOT / "examples" / "topics" / "libraries.json"


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


class FakeResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int = 16384):
        yield b""


class FakeSession:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[str] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **_kwargs: Any) -> FakeResponse:
        self.calls.append(url)
        for needle, payload in self.routes.items():
            if needle in url:
                return FakeResponse(payload)
        raise AssertionError(f"FakeSession had no route matching: {url}")


class ContractSansadCrawler(SansadCrawler):
    def _enrich_askers(self, rec: dict) -> None:
        askers = rec.get("askers") or []
        rec["asker_details"] = [
            {
                "name": name,
                "party": None,
                "party_name": None,
                "house": rec.get("house"),
            }
            for name in askers
        ]
        rec["asker_entity_ids"] = [None for _name in askers]
        rec.setdefault("responder_entity_id", None)
        rec.setdefault("responder_role_at_event", None)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _metadata(value: str) -> list[dict[str, str]]:
    return [{"value": value}]


def _ls_search_payload() -> dict[str, Any]:
    item = {
        "uuid": "uuid-42",
        "handle": "123456789/42",
        "metadata": {
            "dc.date.issued": _metadata("2026-01-01"),
            "dc.identifier.questiontype": _metadata("Unstarred"),
            "dc.identifier.questionnumber": _metadata("42"),
            "dc.identifier.sessionnumber": _metadata("18"),
            "dc.identifier.loksabhanumber": _metadata("18"),
            "dc.title": _metadata("National Mission on Libraries and public libraries"),
            "dc.relation.ministry": _metadata("Culture"),
            "dc.contributor.members": _metadata("MP One"),
            "dc.identifier.uri": _metadata("https://eparlib.nic.in/handle/123456789/42"),
        },
    }
    return {
        "_embedded": {
            "searchResult": {
                "_embedded": {
                    "objects": [{"_embedded": {"indexableObject": item}}],
                },
                "page": {"totalPages": 1},
            },
        },
    }


def _rs_question_row() -> dict[str, Any]:
    return {
        "qslno": "99",
        "ses_no": 261,
        "qtitle": "National Mission on Libraries",
        "ans_date": "02.01.2026",
        "qtype": "Unstarred",
        "qno": "43.0",
        "min_name": "Culture",
        "name": "MP Two",
        "qn_text": "Will the Minister state public library plans?",
        "ans_text": "The National Mission on Libraries supports public libraries.",
        "files": "https://rsdoc.nic.in/q/43.pdf",
        "hindifiles": "https://rsdoc.nic.in/q/43-h.pdf",
        "status": "Answered",
    }


def _committee_record() -> dict[str, Any]:
    return {
        "url": "https://sansad.in/getFile/x/35.pdf",
        "urlH": "https://sansad.in/getFile/h/35.pdf",
        "SubjectOfTheReport": "Demands for Grants and National Mission on Libraries",
        "SubjectOfTheReportH": "",
        "Loksabha": 18,
        "reportNo": 35,
        "CommitteeName": "Finance",
        "PresentedInLS": "17-Mar-2026",
        "LaidInRS": "17-Mar-2026",
        "PresentedToSpeaker": None,
        "dateOfAdoption": None,
        "dateOfPresentation": None,
    }


def test_sansad_local_qa_outputs_keep_semantic_fields_and_parse(tmp_path: Path) -> None:
    topic = ContractTopic()
    crawler = ContractSansadCrawler(
        topic,
        tmp_path,
        sleep=0,
        topic_path=TOPIC_PATH,
        classifier_mode="contract-regex",
    )
    crawler.session = FakeSession(
        {
            "discover/search/objects": _ls_search_payload(),
            "Question/Search_Questions": [_rs_question_row()],
        }
    )

    ls_added = crawler.crawl_ls(
        set(),
        from_date=None,
        to_date=None,
        qtype_filter=None,
        limit=None,
        max_buckets=1,
        max_records=1,
        download=False,
    )
    rs_added = crawler.crawl_rs(
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

    assert (ls_added, rs_added) == (1, 1)
    rows = _read_jsonl(tmp_path / "manifest.jsonl")
    by_house = {row["house"]: row for row in rows}

    ls_row = by_house["Lok Sabha"]
    assert ls_row["kind"] == "qa"
    assert ls_row["found_via_group"] == "libraries"
    assert ls_row["found_via_query"] == "public library"
    assert ls_row["crawled_at"]
    assert ls_row["probed_at"]

    rs_row = by_house["Rajya Sabha"]
    assert rs_row["kind"] == "qa"
    assert rs_row["question_text"] == "Will the Minister state public library plans?"
    assert rs_row["answer_text"] == (
        "The National Mission on Libraries supports public libraries."
    )
    assert rs_row["found_via_query"] == "Culture"

    for row in rows:
        assert row["tags"] == ["nml", "public_library"]
        assert row["matches"] == {
            "nml": ["National Mission on Libraries"],
            "public_library": ["public library"],
        }
        assert row["score"] == 2.0
        assert row["classifier"] == "contract-regex"

    parsed = parse_corpus(topic, tmp_path)
    assert len(parsed) == 2
    for row in parsed:
        assert row["acquisition_source"] == "commoner-probe"
        assert row["acquisition_log"] == "crawl.log"
        assert row["tags"] == ["nml", "public_library"]
        assert row["classifier"] == "contract-regex"
        assert row["text_len"] > 0


def test_committee_local_outputs_keep_report_and_semantic_fields(
    tmp_path: Path,
) -> None:
    topic = ContractTopic()
    crawler = CommitteeCrawler(
        topic,
        tmp_path,
        sleep=0,
        lok_sabha_no=18,
        topic_path=TOPIC_PATH,
        classifier_mode="contract-regex",
    )
    crawler.session = FakeSession(
        {
            "api_ls/committee": {
                "_metadata": {"totalPages": 1},
                "records": [_committee_record()],
            },
        }
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
    row = _read_jsonl(tmp_path / "manifest.jsonl")[0]
    assert row["kind"] == "committee_report"
    assert row["report_type"] == "demands_for_grants"
    assert row["presented_via"] == "both_houses"
    assert row["committee_slug"] == "finance"
    assert row["committee_name"] == "Finance"
    assert row["tags"] == ["nml", "public_library"]
    assert row["matches"] == {
        "nml": ["National Mission on Libraries"],
        "public_library": ["public library"],
    }
    assert row["score"] == 2.0
    assert row["classifier"] == "contract-regex"
    assert row["crawled_at"]
    assert row["probed_at"]

    parsed = parse_corpus(topic, tmp_path)[0]
    assert parsed["acquisition_source"] == "commoner-probe"
    assert parsed["acquisition_log"] == "crawl.log"
    assert parsed["report_type"] == "demands_for_grants"
    assert parsed["tags"] == ["nml", "public_library"]
    assert parsed["classifier"] == "contract-regex"


def test_commoner_probe_sansad_and_committee_rows_normalize_and_parse(
    tmp_path: Path,
) -> None:
    topic = ContractTopic()
    rows = [
        {
            "key": "LS|U|44|2026-01-03",
            "run_id": "a" * 32,
            "kind": "qa",
            "house": "Lok Sabha",
            "uuid": "uuid-44",
            "handle": "123456789/44",
            "title": "National Mission on Libraries and public libraries",
            "date": "2026-01-03",
            "qtype": "Unstarred",
            "qno": "44",
            "session": "18",
            "loksabhanumber": "18",
            "ministry": "Culture",
            "askers": ["MP Three"],
            "asker_details": [{"name": "MP Three", "party": None}],
            "asker_entity_ids": [None],
            "responder_entity_id": None,
            "responder_role_at_event": None,
            "uri": "https://eparlib.nic.in/handle/123456789/44",
            "source": "elibrary.sansad.in",
            "found_via_group": "libraries",
            "found_via_query": "public library",
            "question_text": "Question about public libraries.",
            "answer_text": "Answer about the National Mission on Libraries.",
            "language_classified": ["en"],
            "probed_at": "2026-06-02T12:00:00",
        },
        {
            "key": "LS|finance|35|18",
            "run_id": "b" * 32,
            "house": "Lok Sabha",
            "kind": "committee_report",
            "report_type": "demands_for_grants",
            "presented_via": "both_houses",
            "committee_slug": "finance",
            "committee_name": "Finance",
            "report_no": 35,
            "loksabha_no": 18,
            "title": "Demands for Grants and National Mission on Libraries",
            "language_classified": ["en"],
            "date": "2026-03-17",
            "pdf_url": "https://sansad.in/getFile/x/35.pdf",
            "source": "sansad.in/api_ls/committee",
            "probed_at": "2026-06-02T12:01:00",
        },
    ]
    (tmp_path / "probe.log").write_text("[2026-06-02T12:01:00] done\n", encoding="utf-8")
    _write_jsonl(tmp_path / "manifest.jsonl", rows)

    normalized = list(iter_manifest_records(tmp_path / "manifest.jsonl"))
    assert len(normalized) == 2
    for row in normalized:
        assert row["acquisition_source"] == "commoner-probe"
        assert row["acquisition_log"] == "probe.log"
        assert row["tags"] == []
        assert row["matches"] == {}
        assert row["score"] == 0
        assert row["classifier"] == ""

    parsed = parse_corpus(topic, tmp_path)
    by_key = {row["key"]: row for row in parsed}
    assert by_key["LS|U|44|2026-01-03"]["tags"] == ["nml", "public_library"]
    assert by_key["LS|U|44|2026-01-03"]["classifier"] == "contract-regex"
    assert by_key["LS|finance|35|18"]["report_type"] == "demands_for_grants"
    assert by_key["LS|finance|35|18"]["tags"] == ["nml", "public_library"]
    assert by_key["LS|finance|35|18"]["classifier"] == "contract-regex"
