#!/usr/bin/env python3
"""Bump Billy minor version and prepend a categorized changelog entry."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date
from pathlib import Path
from runpy import run_path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BILLY_PYPROJECT = ROOT / "packages" / "billy" / "pyproject.toml"
BILLY_CHANGELOG = ROOT / "packages" / "billy" / "src" / "billy" / "changelog.py"

VERSION_RE = re.compile(r'^(version\s*=\s*")(\d+)\.(\d+)\.(\d+)(")\s*$', re.MULTILINE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="Release title for this changelog entry.")
    parser.add_argument("--date", default=str(date.today()), help="Release date (YYYY-MM-DD).")
    parser.add_argument("--external", action="append", default=[], help="External MCP change bullet.")
    parser.add_argument("--internal", action="append", default=[], help="Internal MCP change bullet.")
    parser.add_argument("--billy", action="append", default=[], help="Billy change bullet.")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Create a commit after writing version/changelog files.",
    )
    parser.add_argument(
        "--commit-message",
        default=None,
        help="Optional commit message (defaults to 'Release Billy v<version>').",
    )
    return parser.parse_args()


def bump_minor_version(content: str) -> tuple[str, str, str]:
    match = VERSION_RE.search(content)
    if not match:
        raise ValueError(f"Could not find version in {BILLY_PYPROJECT}")

    major = int(match.group(2))
    minor = int(match.group(3))
    old_version = f"{major}.{minor}.{int(match.group(4))}"
    new_version = f"{major}.{minor + 1}.0"
    updated = VERSION_RE.sub(rf'\g<1>{new_version}\g<5>', content, count=1)
    return old_version, new_version, updated


def load_changelog_entries() -> list[dict[str, Any]]:
    namespace = run_path(str(BILLY_CHANGELOG))
    entries = namespace.get("CHANGELOG_ENTRIES")
    if not isinstance(entries, list):
        raise ValueError(f"CHANGELOG_ENTRIES missing or invalid in {BILLY_CHANGELOG}")
    return entries


def render_changelog(entries: list[dict[str, Any]]) -> str:
    payload = json.dumps(entries, indent=4)
    return (
        '"""Versioned changelog entries shipped with Billy."""\n\n'
        "from typing import TypedDict, List\n\n\n"
        "class ChangelogSections(TypedDict):\n"
        "    external_mcp: List[str]\n"
        "    internal_mcp: List[str]\n"
        "    billy: List[str]\n\n\n"
        "class ChangelogEntry(TypedDict):\n"
        "    version: str\n"
        "    date: str\n"
        "    title: str\n"
        "    sections: ChangelogSections\n\n\n"
        "# Newest first. Add one entry for every released version.\n"
        f"CHANGELOG_ENTRIES: List[ChangelogEntry] = {payload}\n"
    )


def run_git_commit(new_version: str, message: str) -> None:
    files = [
        str(BILLY_PYPROJECT.relative_to(ROOT)),
        str(BILLY_CHANGELOG.relative_to(ROOT)),
    ]
    subprocess.run(["git", "add", *files], check=True, cwd=ROOT)
    subprocess.run(["git", "commit", "-m", message], check=True, cwd=ROOT)
    print(f"Committed release for Billy {new_version}")


def main() -> None:
    args = parse_args()
    section_total = len(args.external) + len(args.internal) + len(args.billy)
    if section_total == 0:
        raise SystemExit("Provide at least one change bullet via --external/--internal/--billy.")

    pyproject_content = BILLY_PYPROJECT.read_text()
    old_version, new_version, updated_pyproject = bump_minor_version(pyproject_content)

    new_entry = {
        "version": new_version,
        "date": args.date,
        "title": args.title,
        "sections": {
            "external_mcp": args.external,
            "internal_mcp": args.internal,
            "billy": args.billy,
        },
    }
    entries = [new_entry, *load_changelog_entries()]

    BILLY_PYPROJECT.write_text(updated_pyproject)
    BILLY_CHANGELOG.write_text(render_changelog(entries))

    print(f"Bumped Billy version: {old_version} -> {new_version}")
    print(f"Prepended changelog entry in {BILLY_CHANGELOG.relative_to(ROOT)}")

    if args.commit:
        commit_message = args.commit_message or f"Release Billy v{new_version}"
        run_git_commit(new_version, commit_message)


if __name__ == "__main__":
    main()
