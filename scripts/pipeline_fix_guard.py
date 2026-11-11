"""Decide whether the pipeline doctor's proposed fix may be pushed (#307).

The doctor agent reads untrusted logs, so its output is checked here by fixed code before
anything leaves the runner. Standard library only: the workflow runs a copy taken from
`main` before the patch is applied, with `python3 -I`, so the patch cannot change the guard
that checks it.

    python3 -I pipeline_fix_guard.py paths --base origin/main
    python3 -I pipeline_fix_guard.py branch "$RUN_ID" "$RUN_ATTEMPT"
    python3 -I pipeline_fix_guard.py secrets report.md fix.patch
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ALLOWED_PREFIXES = ("src/", "tests/", "dbt/", "scripts/")
DENIED_PREFIXES = ("src/pulse/contracts/", ".github/")
DENIED_FILES = frozenset(
    {
        "docs/PLAN.md",
        "AGENTS.md",
        "CLAUDE.md",
        "pyproject.toml",
        "dbt/dbt_project.yml",
        "dbt/packages.yml",
        "scripts/pipeline_fix_guard.py",
    }
)
DENIED_SUFFIXES = (".lock",)
# Symlinks and submodules can point a harmless-looking path somewhere else.
DENIED_MODES = {"120000": "symlink", "160000": "submodule"}
BRANCH_PREFIX = "pipeline-fix/"
SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bgh[opsur]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"x-access-token:[^@\s]+@"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_ID = re.compile(r"[1-9][0-9]{0,19}")


@dataclass(frozen=True)
class Change:
    """One entry of `git diff --raw --no-renames`."""

    old_mode: str
    new_mode: str
    status: str
    path: str


def path_violation(path: str) -> str | None:
    """Why the doctor may not change this repo-relative path, or None when it may."""
    parts = path.split("/")
    if not path or path.startswith("/") or "\\" in path:
        return "not a plain repo-relative path"
    if any(part in ("", ".", "..") for part in parts):
        return "path has an empty, '.' or '..' component"
    if any(part.lower() == ".git" for part in parts):
        return "inside .git"
    if path in DENIED_FILES:
        return "protected file"
    if path.startswith(DENIED_PREFIXES):
        return "protected directory"
    if path.endswith(DENIED_SUFFIXES):
        return "lock file"
    if not path.startswith(ALLOWED_PREFIXES):
        return "outside src/, tests/, dbt/ and scripts/"
    return None


def violations(changes: Iterable[Change]) -> list[str]:
    """Every reason to reject the change set. Empty means it may be pushed."""
    found: list[str] = []
    seen = False
    for change in changes:
        seen = True
        reason = path_violation(change.path)
        if reason:
            found.append(f"{change.path}: {reason}")
        for mode in (change.old_mode, change.new_mode):
            if mode in DENIED_MODES:
                found.append(f"{change.path}: {DENIED_MODES[mode]}")
                break
    if not seen:
        found.append("no changes")
    return found


def parse_raw(output: str) -> list[Change]:
    """Parse `git diff --raw -z --no-renames`: a `:meta` field, then the path, NUL-separated."""
    fields = output.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 2:
        raise ValueError("unexpected git diff --raw output")
    changes = []
    for meta, path in zip(fields[::2], fields[1::2], strict=True):
        tokens = meta.lstrip(":").split()
        if len(tokens) != 5:
            raise ValueError(f"unexpected git diff --raw entry: {meta!r}")
        old_mode, new_mode, _old, _new, status = tokens
        changes.append(Change(old_mode, new_mode, status, path))
    return changes


def git_changes(base: str, cwd: Path | None = None) -> list[Change]:
    """The changes from the merge base of `base` to HEAD, with renames split in two."""
    out = subprocess.run(
        ["git", "diff", "--raw", "-z", "--no-renames", "--no-ext-diff", f"{base}...HEAD"],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return parse_raw(out)


def branch_name(run_id: str, run_attempt: str) -> str:
    """`pipeline-fix/<run id>-<attempt>`, from digits only, so no refspec can be smuggled in."""
    for label, value in (("run id", run_id), ("run attempt", run_attempt)):
        if not _ID.fullmatch(value):
            raise ValueError(f"{label} must be a positive integer, got {value!r}")
    return f"{BRANCH_PREFIX}{run_id}-{run_attempt}"


def find_secrets(text: str) -> list[str]:
    """Which secret patterns appear in the text (names only, never the match)."""
    return [p.pattern for p in SECRET_PATTERNS if p.search(text)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    paths = sub.add_parser("paths", help="reject changes outside the allowed paths")
    paths.add_argument("--base", default="origin/main")
    branch = sub.add_parser("branch", help="print the fix branch for a failed run")
    branch.add_argument("run_id")
    branch.add_argument("run_attempt")
    secrets = sub.add_parser("secrets", help="reject files that contain a token")
    secrets.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)

    if args.command == "paths":
        found = violations(git_changes(args.base))
        for reason in found:
            print(f"::error::pipeline fix rejected: {reason}", file=sys.stderr)
        return 1 if found else 0
    if args.command == "branch":
        try:
            print(branch_name(args.run_id, args.run_attempt))
        except ValueError as err:
            print(f"::error::{err}", file=sys.stderr)
            return 1
        return 0
    status = 0
    for file in args.files:
        for pattern in find_secrets(file.read_text(errors="replace")):
            print(f"::error::{file.name} matches secret pattern {pattern}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
