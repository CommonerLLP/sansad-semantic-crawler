"""Bills/debates adoption — SSC delegates acquisition to commoner-probe's new sources.

Mirrors the ``members.py`` delegation pattern: SSC re-exports the probe's ``BillsProbe`` /
``DebateProbe`` and exposes ``crawl-bills`` / ``crawl-debates`` CLI subcommands. There is no SSC
semantic layer for bills/debates yet, so these are thin pass-throughs; this test pins the
wiring and that the probe's record kinds flow through unchanged.

Requires a commoner-probe that ships the new data sources (``commoner_probe.bills`` /
``.debates``); skipped otherwise so older-probe environments don't spuriously fail.
"""

from __future__ import annotations

import pytest

pytest.importorskip("commoner_probe.bills")
pytest.importorskip("commoner_probe.debates")

from commoner_analyse.cli import build_parser  # noqa: E402


def test_reexports_are_probe_symbols():
    import commoner_probe.bills as probe_bills
    import commoner_probe.debates as probe_debates

    from commoner_analyse import bills, debates

    # Re-export, not re-implementation: identical objects (single source of truth).
    assert bills.BillsProbe is probe_bills.BillsProbe
    assert bills.bill_key is probe_bills.bill_key
    assert debates.DebateProbe is probe_debates.DebateProbe
    assert debates.date_to_iso is probe_debates.date_to_iso


def test_cli_registers_new_subcommands():
    parser = build_parser()
    subs = set(parser._subparsers._group_actions[0].choices.keys())  # type: ignore[attr-defined]
    assert {"crawl-bills", "crawl-debates"} <= subs


def test_crawl_bills_dry_run_emits_bill_record_without_writing(tmp_path):
    from commoner_analyse.bills import BillsProbe

    records = BillsProbe(tmp_path, sleep=0, houses=["ls", "rs"]).probe(dry_run=True)

    assert len(records) == 2  # one planning record per house
    assert all(r["kind"] == "bill_record" for r in records)
    assert all(r["fetch_status"] == "dry_run" for r in records)
    assert {r["house"] for r in records} == {"ls", "rs"}
    assert not (tmp_path / "manifest.jsonl").exists()  # dry-run fetches/writes nothing


def test_crawl_bills_cmd_runs_offline(tmp_path, capsys):
    parser = build_parser()
    args = parser.parse_args(["crawl-bills", "--out", str(tmp_path), "--dry-run", "--sleep", "0"])
    args.func(args)
    out = capsys.readouterr().out
    assert "DONE bills (dry-run): 2 planning record(s)" in out


def test_debate_probe_constructible_offline(tmp_path):
    # DebateProbe dry-run fetches the sitting-day catalog (not offline), and the probe's own
    # suite already covers its acquisition. Here we just pin that the re-export is a usable
    # class wired to the corpus dir — fully offline.
    from commoner_analyse.debates import DebateProbe

    probe = DebateProbe(tmp_path, sleep=0, loksabhas=[18])
    assert probe.loksabhas == [18]
    assert probe.manifest == tmp_path / "manifest.jsonl"
