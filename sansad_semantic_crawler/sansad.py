from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import urlencode

from .http_client import make_session
from .runlog import RunLog
from .topics import TopicProfile

LS_API_BASE = "https://elibrary.sansad.in/server/api"
RS_API_SEARCH = "https://rsdoc.nic.in/Question/Search_Questions"
LS_CATEGORY_QA = "Part 1(Questions And Answers)"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 sansad-semantic-crawler/0.1",
}
RS_HEADERS = {
    **HEADERS,
    "Origin": "https://sansad.in",
    "Referer": "https://sansad.in/",
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def stable_key(house: str, qtype: str | None, qno: str | None, date: str | None) -> str:
    h = "LS" if house.lower().startswith("lok") else "RS"
    qt = (qtype or "U").strip().upper()[:1] or "U"
    qn = str(qno or "X").strip().split(".")[0]
    return f"{h}|{qt}|{qn}|{(date or '')[:10]}"


def date_in_range(value: str | None, from_date: str | None, to_date: str | None) -> bool:
    if not value:
        return True
    d = value[:10]
    return not ((from_date and d < from_date) or (to_date and d > to_date))


def md_value(metadata: dict, key: str, default: str = "") -> str:
    arr = metadata.get(key) or []
    if arr and isinstance(arr, list) and isinstance(arr[0], dict):
        return arr[0].get("value", default)
    return default


def md_values(metadata: dict, key: str) -> list[str]:
    arr = metadata.get(key) or []
    return [v.get("value", "") for v in arr if isinstance(v, dict) and v.get("value")]


def rs_date_iso(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.strptime(value.strip()[:10], "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError:
        return value[:10]


class SansadCrawler:
    def __init__(
        self,
        topic: TopicProfile,
        out_dir: Path,
        *,
        sleep: float = 0.25,
        topic_path: Path | str | None = None,
        classifier_mode: str = "regex",
    ):
        self.topic = topic
        self.out_dir = out_dir
        self.pdf_dir = out_dir / "pdfs"
        self.manifest = out_dir / "manifest.jsonl"
        self.log_path = out_dir / "crawl.log"
        self.sleep = sleep
        self.session = make_session()
        # Provenance: each crawl invocation appends to ``_runs.jsonl`` with
        # the topic-profile content hash + classifier configuration so a
        # record can be linked back to the apparatus that produced it.
        # Optional kwargs default safely so legacy callers / tests that
        # construct ``SansadCrawler(topic, out)`` keep working unchanged.
        self.topic_path = topic_path
        self.classifier_mode = classifier_mode
        self.runlog = RunLog(out_dir)

    def log(self, msg: str) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        line = f"[{now()}] {msg}"
        print(line, flush=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def load_seen(self) -> set[str]:
        seen: set[str] = set()
        if not self.manifest.exists():
            return seen
        with self.manifest.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("key"):
                    seen.add(rec["key"])
        return seen

    def append(self, rec: dict) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        with self.manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def ls_search_page(self, query: str, ministry: str, page: int, size: int = 100) -> dict:
        params = [
            ("query", query),
            ("dsoType", "item"),
            ("page", str(page)),
            ("size", str(size)),
            ("f.ministry", f"{ministry},equals"),
            ("f.category", f"{LS_CATEGORY_QA},equals"),
        ]
        url = f"{LS_API_BASE}/discover/search/objects?" + urlencode(params)
        r = self.session.get(url, headers=HEADERS, timeout=45)
        r.raise_for_status()
        return r.json()

    def ls_search_all(self, query: str, ministry: str, limit: int | None) -> Iterator[dict]:
        page = 0
        yielded = 0
        while True:
            data = self.ls_search_page(query, ministry, page=page)
            result = data.get("_embedded", {}).get("searchResult", {})
            objects = result.get("_embedded", {}).get("objects", [])
            if not objects:
                return
            for obj in objects:
                item = obj.get("_embedded", {}).get("indexableObject")
                if not item:
                    continue
                yield item
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
            meta = result.get("page", {})
            if page + 1 >= meta.get("totalPages", 0):
                return
            page += 1
            time.sleep(self.sleep)

    def ls_pdf_url(self, item_uuid: str) -> str | None:
        r = self.session.get(f"{LS_API_BASE}/core/items/{item_uuid}/bundles", headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return None
        bundles = r.json().get("_embedded", {}).get("bundles", [])
        original = next((b for b in bundles if b.get("name") == "ORIGINAL"), None)
        if not original:
            return None
        bitstreams_url = original.get("_links", {}).get("bitstreams", {}).get("href")
        if not bitstreams_url:
            return None
        r2 = self.session.get(bitstreams_url, headers=HEADERS, timeout=30)
        if r2.status_code != 200:
            return None
        bitstreams = r2.json().get("_embedded", {}).get("bitstreams", [])
        pdf = next((b for b in bitstreams if (b.get("name") or "").lower().endswith(".pdf")), None)
        return pdf.get("_links", {}).get("content", {}).get("href") if pdf else None

    def write_pdf(self, url: str, path: Path, headers: dict) -> bool:
        if path.exists() and path.stat().st_size > 1000:
            return True
        path.parent.mkdir(parents=True, exist_ok=True)
        r = self.session.get(url, headers=headers, timeout=120, stream=True)
        if r.status_code != 200:
            return False
        with path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=16384):
                f.write(chunk)
        return path.exists() and path.stat().st_size > 1000

    def crawl_ls(
        self,
        seen: set[str],
        *,
        from_date: str | None,
        to_date: str | None,
        limit: int | None,
        max_buckets: int | None,
        max_records: int | None,
        download: bool,
    ) -> int:
        run_id = self.runlog.start(
            kind="qa",
            scope={
                "house": "ls",
                "from_date": from_date,
                "to_date": to_date,
                "limit": limit,
                "max_buckets": max_buckets,
                "max_records": max_records,
                "download": download,
            },
            topic_name=self.topic.name,
            topic_path=self.topic_path,
            classifier_mode=self.classifier_mode,
            classifier_config=self.topic.classifier_config,
        )
        added = 0
        for group, query in self.topic.searches(max_buckets):
            for ministry in self.topic.lok_sabha_ministries:
                self.log(f"LS query={query!r} ministry={ministry}")
                try:
                    for item in self.ls_search_all(query, ministry, limit):
                        uuid = item.get("uuid")
                        md = item.get("metadata", {})
                        date = md_value(md, "dc.date.issued")
                        qtype = md_value(md, "dc.identifier.questiontype")
                        qno = md_value(md, "dc.identifier.questionnumber")
                        key = stable_key("Lok Sabha", qtype, qno, date)
                        if not uuid or key in seen or not date_in_range(date, from_date, to_date):
                            continue
                        title = md_value(md, "dc.title")
                        semantic = self.topic.classify(title, query)
                        rec = {
                            "key": key,
                            "run_id": run_id,
                            "kind": "qa",
                            "house": "Lok Sabha",
                            "uuid": uuid,
                            "handle": item.get("handle"),
                            "title": title,
                            "date": date,
                            "qtype": qtype,
                            "qno": qno,
                            "session": md_value(md, "dc.identifier.sessionnumber"),
                            "loksabhanumber": md_value(md, "dc.identifier.loksabhanumber"),
                            "ministry": md_value(md, "dc.relation.ministry") or ministry,
                            "askers": md_values(md, "dc.contributor.members"),
                            "uri": md_value(md, "dc.identifier.uri"),
                            "source": "elibrary.sansad.in",
                            "found_via_group": group,
                            "found_via_query": query,
                            "crawled_at": now(),
                            **semantic,
                        }
                        if download:
                            pdf_url = self.ls_pdf_url(uuid)
                            if pdf_url:
                                fname = f"{(qtype or 'U').upper()[:1]}{qno or 'X'}_{uuid[:8].replace('-', '')}.pdf"
                                pdf_path = self.pdf_dir / "ls" / fname
                                if self.write_pdf(pdf_url, pdf_path, HEADERS):
                                    rec["pdf_url"] = pdf_url
                                    rec["pdf_path"] = str(pdf_path.relative_to(self.out_dir))
                        rec.setdefault("language_classified", ["en"])
                        self.append(rec)
                        seen.add(key)
                        added += 1
                        if max_records is not None and added >= max_records:
                            self.runlog.finish(added=added)
                            return added
                        time.sleep(self.sleep)
                except Exception as exc:  # noqa: BLE001
                    self.log(f"LS failed query={query!r} ministry={ministry}: {exc}")
                    self.runlog.record_error(where=f"ls/{ministry}/{query}", exc=exc)
        self.runlog.finish(added=added)
        return added

    def rs_search_session(self, ses_no: int, ministry_like: str) -> list[dict]:
        where = f"ses_no={ses_no} and min_name like '{ministry_like}%'"
        r = self.session.get(RS_API_SEARCH, params={"whereclause": where}, headers=RS_HEADERS, timeout=60)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            return data.get("data", []) or []
        return data if isinstance(data, list) else []

    def crawl_rs(
        self,
        seen: set[str],
        *,
        sessions: Iterable[int],
        from_date: str | None,
        to_date: str | None,
        limit: int | None,
        max_buckets: int | None,
        max_records: int | None,
        download: bool,
    ) -> int:
        sessions_list = list(sessions)
        run_id = self.runlog.start(
            kind="qa",
            scope={
                "house": "rs",
                "sessions": sessions_list,
                "from_date": from_date,
                "to_date": to_date,
                "limit": limit,
                "max_buckets": max_buckets,
                "max_records": max_records,
                "download": download,
            },
            topic_name=self.topic.name,
            topic_path=self.topic_path,
            classifier_mode=self.classifier_mode,
            classifier_config=self.topic.classifier_config,
        )
        added = 0
        ministries = self.topic.rajya_sabha_ministry_likes
        if max_buckets is not None:
            ministries = ministries[:max_buckets]
        for ses_no in sessions_list:
            for ministry in ministries:
                self.log(f"RS session={ses_no} ministry_like={ministry}%")
                try:
                    records = self.rs_search_session(ses_no, ministry)
                except Exception as exc:  # noqa: BLE001
                    self.log(f"RS failed session={ses_no} ministry={ministry}: {exc}")
                    self.runlog.record_error(where=f"rs/{ses_no}/{ministry}", exc=exc)
                    continue
                kept_for_bucket = 0
                for row in records:
                    blob = " ".join(str(row.get(k) or "") for k in ("qtitle", "qn_text", "ans_text"))
                    semantic = self.topic.classify(blob)
                    if not semantic["matches"]:
                        continue
                    date = rs_date_iso(row.get("ans_date"))
                    qtype = (row.get("qtype") or "").strip()
                    qno = str(row.get("qno") or "").split(".")[0]
                    key = stable_key("Rajya Sabha", qtype, qno, date)
                    if key in seen or not date_in_range(date, from_date, to_date):
                        continue
                    rec = {
                        "key": key,
                        "run_id": run_id,
                        "kind": "qa",
                        "house": "Rajya Sabha",
                        "qslno": row.get("qslno"),
                        "ses_no": row.get("ses_no"),
                        "title": (row.get("qtitle") or "").strip(),
                        "date": date,
                        "qtype": qtype,
                        "qno": qno,
                        "ministry": (row.get("min_name") or "").strip(),
                        "askers": [row.get("name")] if row.get("name") else [],
                        "question_text": row.get("qn_text"),
                        "answer_text": row.get("ans_text"),
                        "pdf_url": row.get("files"),
                        "pdf_url_hindi": row.get("hindifiles"),
                        "source": "rsdoc.nic.in",
                        "found_via_query": ministry,
                        "status": (row.get("status") or "").strip(),
                        "crawled_at": now(),
                        **semantic,
                    }
                    if download and rec.get("pdf_url"):
                        fname = f"{(qtype or 'U').upper()[:1]}{qno or 'X'}_{rec.get('qslno')}.pdf"
                        pdf_path = self.pdf_dir / "rs" / fname
                        if self.write_pdf(rec["pdf_url"], pdf_path, RS_HEADERS):
                            rec["pdf_path"] = str(pdf_path.relative_to(self.out_dir))
                    rec.setdefault("language_classified", ["en"])
                    self.append(rec)
                    seen.add(key)
                    added += 1
                    kept_for_bucket += 1
                    if max_records is not None and added >= max_records:
                        self.runlog.finish(added=added)
                        return added
                    if limit is not None and kept_for_bucket >= limit:
                        break
                    time.sleep(self.sleep)
        self.runlog.finish(added=added)
        return added

