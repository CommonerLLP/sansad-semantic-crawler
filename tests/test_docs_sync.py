"""Docs/code consistency checks for public-facing contracts.

These tests intentionally validate narrow factual invariants rather than
snapshotting whole docs files. The goal is to catch drift in version
strings, CLI command names, output-file claims, and discourse-label names.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from commoner_analyse import __version__
from commoner_analyse.cli import build_parser
from commoner_analyse.discourse import DISCOURSE_LABEL_DESCRIPTIONS


REPO_ROOT = Path(__file__).resolve().parent.parent
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
CHANGELOG = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
PYPROJECT = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")


class VersionSyncTests(unittest.TestCase):
    def test_readme_install_lines_match_package_version(self):
        versions = re.findall(
            r"commoner-analyse(?:\[[^]]+\])?\s*@\s*git\+https://github\.com/"
            r"CommonerLLP/commoner-analyse\.git@v([0-9]+\.[0-9]+\.[0-9]+)",
            README,
        )
        self.assertTrue(versions)
        self.assertEqual({__version__}, set(versions))

    def test_pyproject_version_matches_package_version(self):
        match = re.search(r'^version = "([^"]+)"$', PYPROJECT, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(__version__, match.group(1))

    def test_changelog_has_current_version_entry(self):
        self.assertIn(f"## [{__version__}]", CHANGELOG)

    def test_changelog_keeps_unreleased_section(self):
        self.assertIn("## [Unreleased]", CHANGELOG)


class ReadmeCommandSyncTests(unittest.TestCase):
    def test_readme_quick_start_commands_exist_in_cli(self):
        parser = build_parser()
        subcommands = set(parser._subparsers._group_actions[0].choices.keys())  # type: ignore[attr-defined]
        commands = {
            match.group(1)
            for match in re.finditer(r"^\s*commoner-analyse\s+([a-z0-9\-]+)\b", README, re.MULTILINE)
        }
        self.assertTrue(commands)
        self.assertTrue(commands.issubset(subcommands), sorted(commands - subcommands))


class ReadmeDiscourseSyncTests(unittest.TestCase):
    def test_readme_mentions_all_discourse_labels(self):
        labels = {f"`{label}`" for label in DISCOURSE_LABEL_DESCRIPTIONS}
        labels.add("`UNCLASSIFIED`")
        missing = sorted(label for label in labels if label not in README)
        self.assertEqual([], missing)

    def test_readme_does_not_use_stale_discourse_label_names(self):
        self.assertNotIn("DATA_SUBSTITUTION", README)


class ReadmeOutputContractTests(unittest.TestCase):
    def test_readme_mentions_current_output_files(self):
        expected = {
            "manifest.jsonl",
            "_runs.jsonl",
            "analysis.jsonl",
            "answers.jsonl",
            "analysis_discourse.jsonl",
            "atr_linkage.jsonl",
            "mp_summary.jsonl",
            "ministry_summary_qa.jsonl",
            "ministry_summary_committee.jsonl",
            "graph.db",
        }
        missing = sorted(name for name in expected if name not in README)
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
