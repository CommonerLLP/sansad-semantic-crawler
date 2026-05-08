from __future__ import annotations

import argparse
from pathlib import Path

from .committees import CommitteeCrawler, resolve_committees
from .export import build_summary, write_export
from .sansad import SansadCrawler
from .textparse import parse_corpus
from .topics import load_topic


def _split_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [p.strip() for p in value.split(",") if p.strip()]


def parse_session_range(value: str) -> list[int]:
    out: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = [int(x.strip()) for x in part.split("-", 1)]
            out.extend(range(start, end + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def crawl_cmd(args: argparse.Namespace) -> None:
    topic = load_topic(args.topic, classifier_override=args.classifier)
    out = Path(args.out)
    if args.reset and (out / "manifest.jsonl").exists():
        (out / "manifest.jsonl").unlink()
    if args.reset and (out / "crawl.log").exists():
        (out / "crawl.log").unlink()
    effective_mode = args.classifier or topic.classifier_config.get("mode") or "regex"
    crawler = SansadCrawler(
        topic,
        out,
        sleep=args.sleep,
        topic_path=args.topic,
        classifier_mode=effective_mode,
    )
    seen = crawler.load_seen()
    crawler.log(f"resume seen={len(seen)} topic={topic.name} download={not args.no_download}")
    added = 0
    if args.house in ("both", "ls"):
        added += crawler.crawl_ls(
            seen,
            from_date=args.from_date,
            to_date=args.to_date,
            limit=args.limit,
            max_buckets=args.max_buckets,
            max_records=args.max_records,
            download=not args.no_download,
        )
    if args.house in ("both", "rs"):
        added += crawler.crawl_rs(
            seen,
            sessions=parse_session_range(args.sessions),
            from_date=args.from_date,
            to_date=args.to_date,
            limit=args.limit,
            max_buckets=args.max_buckets,
            max_records=args.max_records,
            download=not args.no_download,
        )
    crawler.log(f"DONE added={added} total={len(seen)}")


def crawl_committees_cmd(args: argparse.Namespace) -> None:
    topic = load_topic(args.topic, classifier_override=args.classifier)
    out = Path(args.out)
    if args.reset and (out / "manifest.jsonl").exists():
        (out / "manifest.jsonl").unlink()
    if args.reset and (out / "crawl.log").exists():
        (out / "crawl.log").unlink()
    effective_mode = args.classifier or topic.classifier_config.get("mode") or "regex"
    crawler = CommitteeCrawler(
        topic,
        out,
        sleep=args.sleep,
        lok_sabha_no=args.lok_sabha_no,
        topic_path=args.topic,
        classifier_mode=effective_mode,
    )
    seen = crawler.load_seen()
    requested = _split_csv(args.committees)
    crawler.log(
        f"resume seen={len(seen)} topic={topic.name} ls={args.lok_sabha_no} "
        f"download={not args.no_download}"
    )
    added = 0
    if args.house in ("both", "ls"):
        added += crawler.crawl_ls(
            seen,
            committees=resolve_committees("ls", requested),
            from_date=args.from_date,
            to_date=args.to_date,
            max_records=args.max_records,
            download=not args.no_download,
        )
    if args.house in ("both", "rs"):
        added += crawler.crawl_rs(
            seen,
            committees=resolve_committees("rs", requested),
            from_date=args.from_date,
            to_date=args.to_date,
            max_records=args.max_records,
            download=not args.no_download,
        )
    if args.crawl_composition:
        if args.house in ("both", "ls"):
            crawler.crawl_composition("ls", resolve_committees("ls", requested))
        if args.house in ("both", "rs"):
            crawler.crawl_composition("rs", resolve_committees("rs", requested))
    crawler.log(f"DONE added={added} total={len(seen)}")


def parse_cmd(args: argparse.Namespace) -> None:
    topic = load_topic(args.topic, classifier_override=args.classifier)
    rows = parse_corpus(topic, Path(args.out), refresh_text=args.refresh_text)
    print(f"wrote analysis records={len(rows)}")


def export_cmd(args: argparse.Namespace) -> None:
    topic = load_topic(args.topic, classifier_override=args.classifier)
    out = Path(args.out)
    data = build_summary(topic, out, max_questions=args.max_questions)
    export_path = Path(args.export_path) if args.export_path else out / ("summary.js" if args.format == "js" else "summary.json")
    write_export(data, export_path, fmt=args.format, js_global=args.js_global)
    print(f"wrote {export_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sansad-semantic-crawler")
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl")
    crawl.add_argument("--topic", required=True, help="Path to topic profile JSON")
    crawl.add_argument("--classifier", choices=["regex", "embeddings", "llm", "ensemble"], help="Override profile classifier mode")
    crawl.add_argument("--out", required=True, help="Output corpus directory")
    crawl.add_argument("--house", choices=["both", "ls", "rs"], default="both")
    crawl.add_argument("--from-date")
    crawl.add_argument("--to-date")
    crawl.add_argument("--sessions", default="1-267", help="Rajya Sabha sessions, e.g. 230-267")
    crawl.add_argument("--limit", type=int, help="Max raw API records per bucket")
    crawl.add_argument("--max-buckets", type=int, help="Smoke-test brake: first N search/ministry buckets")
    crawl.add_argument("--max-records", type=int, help="Smoke-test brake: stop after N new records per house crawl")
    crawl.add_argument("--sleep", type=float, default=0.25)
    crawl.add_argument("--no-download", action="store_true")
    crawl.add_argument("--reset", action="store_true")
    crawl.set_defaults(func=crawl_cmd)

    cc = sub.add_parser("crawl-committees", help="Crawl standing-committee reports")
    cc.add_argument("--topic", required=True, help="Path to topic profile JSON")
    cc.add_argument("--classifier", choices=["regex", "embeddings", "llm", "ensemble"], help="Override profile classifier mode")
    cc.add_argument("--out", required=True, help="Output corpus directory")
    cc.add_argument("--house", choices=["both", "ls", "rs"], default="both")
    cc.add_argument("--committees", help="Comma-separated committee slugs; default = all for the chosen house(s)")
    cc.add_argument("--lok-sabha-no", type=int, default=18, help="Lok Sabha number for LS reports (default 18)")
    cc.add_argument("--from-date")
    cc.add_argument("--to-date")
    cc.add_argument("--max-records", type=int, help="Smoke-test brake: stop after N new records per house crawl")
    cc.add_argument("--sleep", type=float, default=0.25)
    cc.add_argument("--no-download", action="store_true")
    cc.add_argument("--crawl-composition", action="store_true", help="Fetch and save committee member lists")
    cc.add_argument("--reset", action="store_true")
    cc.set_defaults(func=crawl_committees_cmd)

    parse = sub.add_parser("parse")
    parse.add_argument("--topic", required=True)
    parse.add_argument("--classifier", choices=["regex", "embeddings", "llm", "ensemble"], help="Override profile classifier mode")
    parse.add_argument("--out", required=True)
    parse.add_argument("--refresh-text", action="store_true")
    parse.set_defaults(func=parse_cmd)

    export = sub.add_parser("export")
    export.add_argument("--topic", required=True)
    export.add_argument("--classifier", choices=["regex", "embeddings", "llm", "ensemble"], help="Override profile classifier mode")
    export.add_argument("--out", required=True)
    export.add_argument("--format", choices=["json", "js"], default="json")
    export.add_argument("--export-path")
    export.add_argument("--js-global", default="SANSAD_TOPIC_DATA")
    export.add_argument("--max-questions", type=int, default=25)
    export.set_defaults(func=export_cmd)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
