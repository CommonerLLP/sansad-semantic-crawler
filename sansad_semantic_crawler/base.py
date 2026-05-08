from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .http_client import make_session
from .runlog import RunLog

if TYPE_CHECKING:
    from .http_client import StdlibSession
    from .resolver import Resolver
    from .topics import TopicProfile


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class BaseCrawler:
    """Shared I/O logic for Sansad crawlers."""

    def __init__(
        self,
        topic: TopicProfile,
        out_dir: Path,
        *,
        sleep: float = 0.25,
        topic_path: Path | str | None = None,
        classifier_mode: str = "regex",
        resolver: "Resolver | None" = None,
    ):
        self.topic = topic
        self.out_dir = out_dir
        self.pdf_dir = out_dir / "pdfs"
        self.manifest = out_dir / "manifest.jsonl"
        self.log_path = out_dir / "crawl.log"
        self.sleep = sleep
        self.session = make_session()
        self.topic_path = topic_path
        self.classifier_mode = classifier_mode
        self.runlog = RunLog(out_dir)
        # Optional name+context -> entity_id resolver. When None, records
        # carry ``asker_entity_ids`` lists with null entries — schema
        # commitment lands either way, populating it requires entity data.
        self.resolver = resolver

    def resolve_askers(self, names: list[str], context: dict | None = None) -> list[str | None]:
        """Map a list of asker names to a parallel list of entity_ids.

        Same length as input. Null entries mean ``status != "resolved"`` —
        unknown name, ambiguous match, or no resolver configured. The
        record stays honest about the gap; consumers handling weights and
        cross-session tracking skip null entities cleanly.
        """
        out: list[str | None] = []
        for nm in names or []:
            if not self.resolver:
                out.append(None)
                continue
            result = self.resolver.resolve(nm, context=context, kind_hint="mp")
            out.append(result.entity_id if result.status == "resolved" else None)
        return out

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

    def write_pdf(self, url: str, dest_path: Path, headers: dict) -> bool:
        if dest_path.exists() and dest_path.stat().st_size > 1000:
            return True
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            r = self.session.get(url, headers=headers, timeout=60)
            r.raise_for_status()
            with dest_path.open("wb") as f:
                for chunk in r.iter_content(chunk_size=16384):
                    f.write(chunk)
            return dest_path.exists() and dest_path.stat().st_size > 1000
        except Exception as e:
            self.log(f"Warning: Failed to download PDF {url}: {e}")
            return False
