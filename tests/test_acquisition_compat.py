from __future__ import annotations

import argparse

from commoner_analyse.acquisition_compat import (
    build_commoner_probe_command,
    deprecation_message,
)


def test_crawl_replacement_maps_to_commoner_probe_sansad_without_classifier():
    args = argparse.Namespace(
        topic="topics/libraries.json",
        out="data/libraries",
        house="ls",
        from_date="2024-01-01",
        to_date=None,
        qtype="starred",
        sessions="250-267",
        limit=10,
        max_buckets=2,
        max_records=5,
        sleep=0.1,
        no_download=True,
        reset=True,
        with_entities=True,
        classifier="regex",
    )

    command = build_commoner_probe_command("crawl", args)

    assert command == [
        "commoner-probe",
        "sansad",
        "--topic",
        "topics/libraries.json",
        "--out",
        "data/libraries",
        "--house",
        "ls",
        "--from-date",
        "2024-01-01",
        "--qtype",
        "starred",
        "--sessions",
        "250-267",
        "--limit",
        "10",
        "--max-buckets",
        "2",
        "--max-records",
        "5",
        "--sleep",
        "0.1",
        "--no-download",
        "--reset",
        "--with-entities",
    ]
    assert "--classifier" not in command


def test_committees_replacement_omits_classifier_and_composition_flags():
    args = argparse.Namespace(
        topic="topics/libraries.json",
        out="data/libraries",
        house="rs",
        committees="health,education",
        lok_sabha_no=18,
        from_date=None,
        to_date="2026-01-01",
        max_records=4,
        sleep=0.2,
        no_download=False,
        reset=False,
        classifier="regex",
        crawl_composition=True,
    )

    command = build_commoner_probe_command("crawl-committees", args)

    assert command == [
        "commoner-probe",
        "committees",
        "--topic",
        "topics/libraries.json",
        "--out",
        "data/libraries",
        "--house",
        "rs",
        "--committees",
        "health,education",
        "--lok-sabha-no",
        "18",
        "--to-date",
        "2026-01-01",
        "--max-records",
        "4",
        "--sleep",
        "0.2",
    ]
    assert "--classifier" not in command
    assert "--crawl-composition" not in command


def test_neva_replacement_renames_state_code_to_state_assembly():
    args = argparse.Namespace(
        portal="gujarat",
        state_code="GJ",
        out="data/neva/gujarat",
        assemblies="14,15",
        sleep=0.5,
        no_download=True,
        no_member_details=True,
        sessions_limit=2,
    )

    command = build_commoner_probe_command("neva-crawl", args)

    assert command == [
        "commoner-probe",
        "state-assembly",
        "--portal",
        "gujarat",
        "--state",
        "GJ",
        "--out",
        "data/neva/gujarat",
        "--assemblies",
        "14,15",
        "--sleep",
        "0.5",
        "--no-download",
        "--no-member-details",
        "--sessions-limit",
        "2",
    ]


def test_deprecation_message_names_local_compatibility_and_commoner_probe():
    args = argparse.Namespace(
        topic="topic.json",
        out="data/out",
        house="both",
        from_date=None,
        to_date=None,
        qtype="both",
        sessions="1-267",
        limit=None,
        max_buckets=None,
        max_records=None,
        sleep=0.25,
        no_download=False,
        reset=False,
        with_entities=False,
    )

    message = deprecation_message("crawl", args)

    assert "deprecated acquisition command" in message
    assert "commoner-probe sansad" in message
    assert "local compatibility crawler" in message
