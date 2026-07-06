from __future__ import annotations

import argparse
import shlex
import sys
from typing import Any


def _value(args: argparse.Namespace, name: str) -> Any:
    return getattr(args, name, None)


def _append_option(command: list[str], flag: str, value: Any) -> None:
    if value is None:
        return
    command.extend([flag, str(value)])


def _append_flag(command: list[str], flag: str, enabled: bool) -> None:
    if enabled:
        command.append(flag)


def build_commoner_probe_command(command_name: str, args: argparse.Namespace) -> list[str]:
    if command_name == "crawl":
        command = ["commoner-probe", "sansad"]
        _append_option(command, "--topic", _value(args, "topic"))
        _append_option(command, "--out", _value(args, "out"))
        _append_option(command, "--house", _value(args, "house"))
        _append_option(command, "--from-date", _value(args, "from_date"))
        _append_option(command, "--to-date", _value(args, "to_date"))
        _append_option(command, "--qtype", _value(args, "qtype"))
        _append_option(command, "--sessions", _value(args, "sessions"))
        _append_option(command, "--limit", _value(args, "limit"))
        _append_option(command, "--max-buckets", _value(args, "max_buckets"))
        _append_option(command, "--max-records", _value(args, "max_records"))
        _append_option(command, "--sleep", _value(args, "sleep"))
        _append_flag(command, "--no-download", bool(_value(args, "no_download")))
        _append_flag(command, "--reset", bool(_value(args, "reset")))
        _append_flag(command, "--with-entities", bool(_value(args, "with_entities")))
        return command

    if command_name == "crawl-committees":
        command = ["commoner-probe", "committees"]
        _append_option(command, "--topic", _value(args, "topic"))
        _append_option(command, "--out", _value(args, "out"))
        _append_option(command, "--house", _value(args, "house"))
        _append_option(command, "--committees", _value(args, "committees"))
        _append_option(command, "--lok-sabha-no", _value(args, "lok_sabha_no"))
        _append_option(command, "--from-date", _value(args, "from_date"))
        _append_option(command, "--to-date", _value(args, "to_date"))
        _append_option(command, "--max-records", _value(args, "max_records"))
        _append_option(command, "--sleep", _value(args, "sleep"))
        _append_flag(command, "--no-download", bool(_value(args, "no_download")))
        _append_flag(command, "--reset", bool(_value(args, "reset")))
        return command

    if command_name == "neva-crawl":
        command = ["commoner-probe", "state-assembly"]
        _append_option(command, "--portal", _value(args, "portal"))
        _append_option(command, "--state", _value(args, "state_code"))
        _append_option(command, "--out", _value(args, "out"))
        _append_option(command, "--assemblies", _value(args, "assemblies"))
        _append_option(command, "--sleep", _value(args, "sleep"))
        _append_flag(command, "--no-download", bool(_value(args, "no_download")))
        _append_flag(command, "--no-member-details", bool(_value(args, "no_member_details")))
        _append_option(command, "--sessions-limit", _value(args, "sessions_limit"))
        return command

    raise ValueError(f"unknown acquisition command: {command_name}")


def deprecation_message(command_name: str, args: argparse.Namespace) -> str:
    replacement = shlex.join(build_commoner_probe_command(command_name, args))
    notes: list[str] = []
    if _value(args, "classifier"):
        notes.append("--classifier has no commoner-probe equivalent; run parse/analyse here after acquisition.")
    if _value(args, "crawl_composition"):
        notes.append("--crawl-composition remains local until commoner-probe exposes a stable CLI flag.")
    detail = "\n".join(f"  - {note}" for note in notes)
    if detail:
        detail = "\n" + detail
    return (
        f"warning: commoner-analyse {command_name} is a deprecated acquisition command.\n"
        f"new acquisition belongs to commoner-probe:\n  {replacement}\n"
        f"the local compatibility crawler will still run in this release to preserve "
        f"existing manifest contracts.{detail}"
    )


def warn_deprecated_acquisition(command_name: str, args: argparse.Namespace) -> None:
    print(deprecation_message(command_name, args), file=sys.stderr)
