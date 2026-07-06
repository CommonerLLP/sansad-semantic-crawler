from __future__ import annotations

import argparse
from pathlib import Path

from .acquisition_compat import warn_deprecated_acquisition
from .aggregations import write_ministry_summary, write_mp_summary
from .graph import build_graph
from .answers import extract_answers
from .atr_linkage import extract_atr_linkages
from .committees import CommitteeCrawler, resolve_committees
from .discourse import analyse_discourse
from .dossier import build_ministry_dossier, build_mp_dossier, build_question_refinement
from .export import build_summary, write_export
from .neva import NevaStateCrawler
from .sansad import SansadCrawler
from .textparse import parse_corpus
from .topics import load_topic
from .weighting import compute_weights


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


def _build_resolver_if_requested(out_dir: Path, with_entities: bool, log):
    """Lazy-import to keep the CLI cold-start cheap when --with-entities is off."""
    if not with_entities:
        return None
    from .entities import EntityStore, populate_entity_store_from_mp_roster
    from .members import MPRoster
    from .resolver import Resolver
    store = EntityStore(out_dir)
    store.load()
    if not store.people:
        log("Entity store empty — fetching MP roster from sansad.in...")
        roster = MPRoster()
        try:
            roster.load_ls()
            roster.load_rs()
        except Exception as exc:  # noqa: BLE001
            log(f"Warning: MP roster fetch failed: {exc}; resolver will return 'unknown' for askers.")
        people_added, memberships_added = populate_entity_store_from_mp_roster(roster, store)
        log(f"Populated entity store: {people_added} people, {memberships_added} memberships.")
        store.save()
    else:
        log(f"Loaded existing entity store: {len(store.people)} people.")
    return Resolver(store)


def crawl_cmd(args: argparse.Namespace) -> None:
    warn_deprecated_acquisition("crawl", args)
    topic = load_topic(args.topic, classifier_override=args.classifier)
    out = Path(args.out)
    if args.reset and (out / "manifest.jsonl").exists():
        (out / "manifest.jsonl").unlink()
    if args.reset and (out / "crawl.log").exists():
        (out / "crawl.log").unlink()
    effective_mode = args.classifier or topic.classifier_config.get("mode") or "regex"
    out.mkdir(parents=True, exist_ok=True)
    resolver = _build_resolver_if_requested(out, getattr(args, "with_entities", False), print)
    crawler = SansadCrawler(
        topic,
        out,
        sleep=args.sleep,
        topic_path=args.topic,
        classifier_mode=effective_mode,
        resolver=resolver,
    )
    seen = crawler.load_seen()
    crawler.log(f"resume seen={len(seen)} topic={topic.name} download={not args.no_download}")
    added = 0
    if args.house in ("both", "ls"):
        added += crawler.crawl_ls(
            seen,
            from_date=args.from_date,
            to_date=args.to_date,
            qtype_filter=None if args.qtype == "both" else args.qtype,
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
            qtype_filter=None if args.qtype == "both" else args.qtype,
            limit=args.limit,
            max_buckets=args.max_buckets,
            max_records=args.max_records,
            download=not args.no_download,
        )
    crawler.log(f"DONE added={added} total={len(seen)}")


def crawl_committees_cmd(args: argparse.Namespace) -> None:
    warn_deprecated_acquisition("crawl-committees", args)
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


def crawl_bills_cmd(args: argparse.Namespace) -> None:
    # Lazy import: commoner_probe.bills ships in the probe's new-data-sources release, newer
    # than the committee/Q-A surface. Importing here (not at module top) keeps the rest of the
    # CLI working against an older probe — same approach as members in the entity resolver.
    from .bills import BillsProbe

    out = Path(args.out)
    if args.reset and (out / "manifest.jsonl").exists():
        (out / "manifest.jsonl").unlink()
    houses = [args.house] if args.house != "both" else ["ls", "rs"]
    probe = BillsProbe(
        out,
        sleep=args.sleep,
        houses=houses,
        bill_type=args.bill_type,
        **({"api_url": args.api_url} if args.api_url else {}),
    )
    records = probe.probe(max_records=args.max_records, dry_run=args.dry_run)
    if args.dry_run:
        print(f"DONE bills (dry-run): {len(records)} planning record(s), nothing written")
    else:
        print(f"DONE bills added={len(records)} -> {out}/manifest.jsonl")


def crawl_debates_cmd(args: argparse.Namespace) -> None:
    from .debates import DebateProbe  # lazy — see crawl_bills_cmd

    out = Path(args.out)
    if args.reset and (out / "manifest.jsonl").exists():
        (out / "manifest.jsonl").unlink()
    loksabhas = [int(x) for x in (_split_csv(args.loksabhas) or ["18"])]
    sessions = [int(x) for x in (_split_csv(args.sessions) or [])] or None
    probe = DebateProbe(
        out,
        sleep=args.sleep,
        loksabhas=loksabhas,
        sessions=sessions,
        from_date=args.from_date,
        to_date=args.to_date,
        **({"api_url": args.api_url} if args.api_url else {}),
    )
    records = probe.probe(
        max_records=args.max_records,
        download=args.download,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(f"DONE debates (dry-run): {len(records)} candidate record(s), nothing written")
    else:
        print(f"DONE debates added={len(records)} -> {out}/manifest.jsonl")


def extract_answers_cmd(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if not (out / "manifest.jsonl").exists():
        raise SystemExit(f"no manifest at {out}/manifest.jsonl — run 'crawl' first")
    extract_answers(out, refresh=args.refresh, log_fn=print)


def analyse_discourse_cmd(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if not (out / "answers.jsonl").exists():
        raise SystemExit(
            f"no answers.jsonl at {out}/answers.jsonl — run 'extract-answers' first"
        )
    analyse_discourse(
        out,
        refresh=args.refresh,
        log_fn=print,
        llm_tier=args.llm_tier,
        llm_endpoint=args.llm_endpoint,
        llm_model=args.llm_model,
        llm_timeout_s=args.llm_timeout,
        llm_api_key=args.llm_api_key,
        llm_allow_private=not args.llm_block_private,
    )


def analyse_weights_cmd(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if not (out / "analysis_discourse.jsonl").exists():
        raise SystemExit(
            f"no analysis_discourse.jsonl at {out}/analysis_discourse.jsonl — "
            f"run 'analyse-discourse' first"
        )
    compute_weights(out, topic_profile_path=args.topic, shrinkage_n0=args.shrinkage_n0, log_fn=print)


def extract_atr_linkage_cmd(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if not (out / "manifest.jsonl").exists():
        raise SystemExit(f"no manifest at {out}/manifest.jsonl — run 'crawl-committees' first")
    extract_atr_linkages(out, log_fn=print)


def mp_summary_cmd(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if not (out / "manifest.jsonl").exists():
        raise SystemExit(f"no manifest at {out}/manifest.jsonl — run 'crawl' first")
    topic_path = Path(args.topic) if args.topic else None
    write_mp_summary(out, topic_profile_path=topic_path, log_fn=print)


def analyse_ministry_cmd(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if not (out / "manifest.jsonl").exists():
        raise SystemExit(f"no manifest at {out}/manifest.jsonl — run 'crawl' / 'crawl-committees' first")
    topic_path = Path(args.topic) if args.topic else None
    write_ministry_summary(out, topic_profile_path=topic_path, log_fn=print)


def mp_dossier_cmd(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if not (out / "manifest.jsonl").exists():
        raise SystemExit(f"no manifest at {out}/manifest.jsonl — run 'crawl' first")
    if not args.entity_id and not args.name:
        raise SystemExit("either --entity-id or --name is required")
    topic_path = Path(args.topic) if args.topic else None
    build_mp_dossier(
        out,
        entity_id=args.entity_id,
        name=args.name,
        topic_profile_path=topic_path,
        log_fn=print,
    )


def ministry_dossier_cmd(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if not (out / "manifest.jsonl").exists():
        raise SystemExit(f"no manifest at {out}/manifest.jsonl — run 'crawl' first")
    if not args.ministry:
        raise SystemExit("--ministry is required")
    topic_path = Path(args.topic) if args.topic else None
    build_ministry_dossier(
        out,
        ministry=args.ministry,
        topic_profile_path=topic_path,
        log_fn=print,
    )


def question_refine_cmd(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if not (out / "manifest.jsonl").exists():
        raise SystemExit(f"no manifest at {out}/manifest.jsonl — run 'crawl' first")
    if not args.query:
        raise SystemExit("--query is required")
    build_question_refinement(
        out,
        query=args.query,
        llm_tier=args.llm_tier,
        endpoint=args.llm_endpoint,
        model=args.llm_model,
        timeout_s=args.llm_timeout,
        api_key=args.llm_api_key,
        allow_private=not args.llm_block_private,
        max_precedents=args.max_precedents,
        log_fn=print,
    )


def build_graph_cmd(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if not out.is_dir():
        raise SystemExit(f"output directory does not exist: {out}")
    db_path = Path(args.db) if args.db else None
    build_graph(out, db_path=db_path, log_fn=print)


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


def neva_crawl_cmd(args: argparse.Namespace) -> None:
    warn_deprecated_acquisition("neva-crawl", args)
    assembly_nos = [int(x.strip()) for x in args.assemblies.split(",") if x.strip()]
    crawler = NevaStateCrawler(
        args.portal,
        args.state_code,
        Path(args.out),
        sleep=args.sleep,
    )
    crawler.run(
        assembly_nos,
        download=not args.no_download,
        fetch_member_details=not args.no_member_details,
        sessions_limit=args.sessions_limit,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="commoner-analyse")
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl")
    crawl.add_argument("--topic", required=True, help="Path to topic profile JSON")
    crawl.add_argument("--classifier", choices=["regex", "embeddings", "llm", "ensemble"], help="Override profile classifier mode")
    crawl.add_argument("--out", required=True, help="Output corpus directory")
    crawl.add_argument("--house", choices=["both", "ls", "rs"], default="both")
    crawl.add_argument("--from-date")
    crawl.add_argument("--to-date")
    crawl.add_argument(
        "--qtype",
        choices=["both", "starred", "unstarred"],
        default="both",
        help="Filter to starred or unstarred questions at crawl time.",
    )
    crawl.add_argument("--sessions", default="1-267", help="Rajya Sabha sessions, e.g. 230-267")
    crawl.add_argument("--limit", type=int, help="Max raw API records per bucket")
    crawl.add_argument("--max-buckets", type=int, help="Smoke-test brake: first N search/ministry buckets")
    crawl.add_argument("--max-records", type=int, help="Smoke-test brake: stop after N new records per house crawl")
    crawl.add_argument("--sleep", type=float, default=0.25)
    crawl.add_argument("--no-download", action="store_true")
    crawl.add_argument("--reset", action="store_true")
    crawl.add_argument(
        "--with-entities",
        action="store_true",
        help=(
            "Resolve asker names to stable entity_ids. First run fetches MP "
            "rosters from sansad.in and populates entities/people.jsonl + "
            "entities/mp_memberships.jsonl; subsequent runs reuse the local "
            "store. Without this flag, asker_entity_ids on every record are "
            "all None (schema commitment intact, resolution skipped)."
        ),
    )
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

    cb = sub.add_parser(
        "crawl-bills",
        help="Crawl sansad.in bills/legislation (acquisition delegated to commoner-probe)",
    )
    cb.add_argument("--out", required=True, help="Output corpus directory")
    cb.add_argument("--house", choices=["both", "ls", "rs"], default="both")
    cb.add_argument(
        "--bill-type",
        default="",
        help="Filter by bill type, e.g. 'Government' or 'Private Member'; default = all types",
    )
    cb.add_argument("--max-records", type=int, help="Smoke-test brake: stop after N new records per house")
    cb.add_argument("--api-url", help="Override the bills API base URL")
    cb.add_argument("--sleep", type=float, default=0.5)
    cb.add_argument("--reset", action="store_true")
    cb.add_argument("--dry-run", action="store_true", help="Emit one planning record per house without fetching")
    cb.set_defaults(func=crawl_bills_cmd)

    cd = sub.add_parser(
        "crawl-debates",
        help="Crawl Lok Sabha per-day floor-debate transcript PDFs (delegated to commoner-probe)",
    )
    cd.add_argument("--out", required=True, help="Output corpus directory")
    cd.add_argument("--loksabhas", default="18", help="Comma-separated Lok Sabha numbers, e.g. 17,18")
    cd.add_argument("--sessions", help="Comma-separated session numbers; default = all")
    cd.add_argument("--from-date", help="ISO date lower bound (YYYY-MM-DD)")
    cd.add_argument("--to-date", help="ISO date upper bound (YYYY-MM-DD)")
    cd.add_argument("--max-records", type=int, help="Smoke-test brake: stop after N new records per Lok Sabha")
    cd.add_argument("--download", action="store_true", help="Download each day's transcript PDF (+ sha256)")
    cd.add_argument("--api-url", help="Override the debate API base URL")
    cd.add_argument("--sleep", type=float, default=0.5)
    cd.add_argument("--reset", action="store_true")
    cd.add_argument("--dry-run", action="store_true", help="List candidate sitting dates without fetching per-day PDFs")
    cd.set_defaults(func=crawl_debates_cmd)

    extract = sub.add_parser(
        "extract-answers",
        help="Extract structured (question/answer) and (recommendation/response) pairs from PDFs into answers.jsonl",
    )
    extract.add_argument("--out", required=True, help="Corpus directory containing manifest.jsonl + downloaded PDFs")
    extract.add_argument("--refresh", action="store_true", help="Force re-extraction even if answers.jsonl exists")
    extract.set_defaults(func=extract_answers_cmd)

    analyse = sub.add_parser(
        "analyse-discourse",
        help=(
            "Classify ministry responses by political function "
            "(ACCEPTED/DEFLECTED/ABSORBED/REJECTED/SUBSTITUTED/DATA_WITHHELD/"
            "SCOPE_NARROWED/CIRCULAR_REFERENCE/FACTUAL_DISCLOSURE) into "
            "analysis_discourse.jsonl. Use --llm-tier to pass UNCLASSIFIED "
            "records to a local Ollama model as a second-pass classifier."
        ),
    )
    analyse.add_argument("--out", required=True, help="Corpus directory containing answers.jsonl")
    analyse.add_argument("--refresh", action="store_true")
    analyse.add_argument(
        "--llm-tier",
        action="store_true",
        help=(
            "Enable LLM second-pass for UNCLASSIFIED records. Requires a "
            "running Ollama instance at --llm-endpoint (default "
            "http://localhost:11434/v1)."
        ),
    )
    analyse.add_argument(
        "--llm-endpoint",
        default="http://localhost:11434/v1",
        help="OpenAI-compatible chat completions base URL (default: Ollama localhost).",
    )
    analyse.add_argument(
        "--llm-model",
        default="qwen2.5:7b",
        help="Model name for the LLM tier (default: qwen2.5:7b).",
    )
    analyse.add_argument(
        "--llm-timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds for each LLM request (default: 30).",
    )
    analyse.add_argument(
        "--llm-api-key",
        default=None,
        help=(
            "Bearer token for the LLM endpoint. Use 'env:VAR_NAME' to read "
            "from an environment variable (recommended). Default: no auth "
            "header sent (correct for local Ollama)."
        ),
    )
    analyse.add_argument(
        "--llm-block-private",
        action="store_true",
        help=(
            "Reject loopback / private / link-local LLM endpoint hosts. "
            "Use this for hardened deployments where the LLM tier should "
            "only call out to public/managed endpoints. Default: allowed "
            "so local Ollama works zero-config."
        ),
    )
    analyse.set_defaults(func=analyse_discourse_cmd)

    weights = sub.add_parser(
        "analyse-weights",
        help=(
            "Compute per-person and per-party weights from "
            "analysis_discourse.jsonl + entities/. Writes "
            "weights/{person,party}_topic.jsonl with full lineage."
        ),
    )
    weights.add_argument("--out", required=True, help="Corpus directory")
    weights.add_argument("--topic", required=True, help="Topic profile JSON (for topic_hash provenance)")
    weights.add_argument(
        "--shrinkage-n0",
        type=float,
        default=10.0,
        help=(
            "Bayesian shrinkage strength: pseudo-count of the party prior "
            "in the posterior. Default 10. Higher = more conservative for "
            "small samples (more pull toward party average). 0 = no shrinkage."
        ),
    )
    weights.set_defaults(func=analyse_weights_cmd)

    atr_link = sub.add_parser(
        "extract-atr-linkage",
        help=(
            "For every Action Taken Report in manifest.jsonl, parse the title "
            "to find the original report it cites. Writes atr_linkage.jsonl with "
            "atr_no -> referenced_report_no mappings."
        ),
    )
    atr_link.add_argument("--out", required=True, help="Corpus directory containing manifest.jsonl")
    atr_link.set_defaults(func=extract_atr_linkage_cmd)

    bg = sub.add_parser(
        "build-graph",
        help=(
            "Ingest pipeline outputs (answers.jsonl, analysis_discourse.jsonl, "
            "entities/people.jsonl, atr_linkage.jsonl) into a single SQLite "
            "database for fast cross-file queries. Writes graph.db by default. "
            "Rebuild is skipped automatically if inputs haven't changed."
        ),
    )
    bg.add_argument("--out", required=True, help="Corpus directory containing pipeline outputs")
    bg.add_argument("--db", help="Path for the SQLite database (default: <out>/graph.db)")
    bg.set_defaults(func=build_graph_cmd)

    mp_sum = sub.add_parser(
        "mp-summary",
        help=(
            "Aggregate per-MP question count + ministries asked + response-label "
            "distribution from manifest.jsonl + analysis_discourse.jsonl. "
            "Writes mp_summary.jsonl."
        ),
    )
    mp_sum.add_argument("--out", required=True, help="Corpus directory")
    mp_sum.add_argument(
        "--topic",
        help="Topic profile JSON (for topic_hash provenance on each row).",
    )
    mp_sum.set_defaults(func=mp_summary_cmd)

    min_sum = sub.add_parser(
        "analyse-ministry",
        help=(
            "Aggregate per-ministry (Q/A) and per-committee (committee reports) "
            "response patterns: total records, label distribution, evasion rate, "
            "per-evasion-label share, and rejected recommendation keys. "
            "Writes ministry_summary_qa.jsonl + ministry_summary_committee.jsonl."
        ),
    )
    min_sum.add_argument("--out", required=True, help="Corpus directory")
    min_sum.add_argument(
        "--topic",
        help="Topic profile JSON (for topic_hash provenance on each row).",
    )
    min_sum.set_defaults(func=analyse_ministry_cmd)

    dossier = sub.add_parser(
        "mp-dossier",
        help=(
            "Generate a Markdown briefing for a single MP — every question "
            "they asked in the corpus, grouped by topic, with response-label "
            "distribution and excerpts of evasion text. Reads structured "
            "fields from answers.jsonl (v0.6.5+) and discourse labels from "
            "analysis_discourse.jsonl. Output: mp_dossiers/<slug>.md"
        ),
    )
    dossier.add_argument("--out", required=True, help="Corpus directory")
    dossier.add_argument(
        "--entity-id",
        help="Stable entity_id from entities/people.jsonl (preferred when known).",
    )
    dossier.add_argument(
        "--name",
        help="Loose-match MP name (case-insensitive substring; surname-aware).",
    )
    dossier.add_argument(
        "--topic",
        help="Topic profile JSON (recorded in dossier provenance).",
    )
    dossier.set_defaults(func=mp_dossier_cmd)

    ministry_dossier = sub.add_parser(
        "ministry-dossier",
        help=(
            "Generate a Markdown briefing for one ministry — every QA record "
            "addressed to that ministry in the corpus, grouped by topic, "
            "with question-type counts, answering-minister distribution, and "
            "response-label excerpts. Output: ministry_dossiers/<slug>.md"
        ),
    )
    ministry_dossier.add_argument("--out", required=True, help="Corpus directory")
    ministry_dossier.add_argument(
        "--ministry",
        required=True,
        help="Ministry name or loose fragment (case-insensitive substring match).",
    )
    ministry_dossier.add_argument(
        "--topic",
        help="Topic profile JSON (recorded in dossier provenance).",
    )
    ministry_dossier.set_defaults(func=ministry_dossier_cmd)

    question_refine = sub.add_parser(
        "question-refine",
        help=(
            "Refine a rough parliamentary research prompt into a structured "
            "draft with parsed facets, answer-style risk, and corpus precedents. "
            "Writes question_refinements/<slug>.md and .json."
        ),
    )
    question_refine.add_argument("--out", required=True, help="Corpus directory")
    question_refine.add_argument("--query", required=True, help="Free-text research prompt")
    question_refine.add_argument(
        "--max-precedents",
        type=int,
        default=5,
        help="Maximum precedents to surface in the refinement bundle.",
    )
    question_refine.add_argument(
        "--llm-tier",
        action="store_true",
        help="Enable LLM fallback for ambiguous facet parsing.",
    )
    question_refine.add_argument(
        "--llm-endpoint",
        default="http://localhost:11434/v1",
        help="OpenAI-compatible chat completions base URL (default: Ollama localhost).",
    )
    question_refine.add_argument(
        "--llm-model",
        default="qwen2.5:7b",
        help="Model name for the LLM tier (default: qwen2.5:7b).",
    )
    question_refine.add_argument(
        "--llm-timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds for each LLM request (default: 30).",
    )
    question_refine.add_argument(
        "--llm-api-key",
        default=None,
        help=(
            "Bearer token for the LLM endpoint. Use 'env:VAR_NAME' to read "
            "from an environment variable (recommended). Default: no auth "
            "header sent (correct for local Ollama)."
        ),
    )
    question_refine.add_argument(
        "--llm-block-private",
        action="store_true",
        help=(
            "Reject loopback / private / link-local LLM endpoint hosts. "
            "Use this for hardened deployments where the LLM tier should "
            "only call out to public/managed endpoints. Default: allowed "
            "so local Ollama works zero-config."
        ),
    )
    question_refine.set_defaults(func=question_refine_cmd)

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

    neva = sub.add_parser(
        "neva-crawl",
        help=(
            "Crawl a NeVA (National e-Vidhan Application) state assembly portal. "
            "Fetches questions, members, and papers to be laid."
        ),
    )
    neva.add_argument("--portal", required=True, help="Portal subdomain, e.g. 'gujarat'")
    neva.add_argument("--state-code", required=True, help="CMS two-letter code, e.g. 'GJ'")
    neva.add_argument("--assemblies", required=True, help="Comma-separated assembly numbers, e.g. '15' or '14,15'")
    neva.add_argument("--out", required=True, help="Output directory")
    neva.add_argument("--sleep", type=float, default=0.5, help="Seconds between requests (default 0.5)")
    neva.add_argument("--no-download", action="store_true", help="Skip PDF downloads")
    neva.add_argument("--no-member-details", action="store_true", help="Skip per-member detail page fetches")
    neva.add_argument("--sessions-limit", type=int, help="Smoke-test: stop after N sessions per assembly")
    neva.set_defaults(func=neva_crawl_cmd)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
