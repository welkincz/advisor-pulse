"""Budgeted, atomic publication of immutable static-report versions."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

DEFAULT_TOTAL_BYTES = 20_000_000
DEFAULT_FILE_BYTES = 10_000_000


class ExportBudgetError(ValueError):
    """An export exceeded its per-file or total byte budget."""


def check_budget(root: Path, *, max_file_bytes: int, max_total_bytes: int) -> None:
    """Check every staged file and their combined size before publication."""
    if max_file_bytes < 1 or max_total_bytes < 1:
        raise ValueError("export byte budgets must be positive")
    total = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size > max_file_bytes:
            raise ExportBudgetError(f"{path.relative_to(root)} exceeds per-file byte budget")
        total += size
    if total > max_total_bytes:
        raise ExportBudgetError(f"Export is {total} bytes, above {max_total_bytes} byte budget")


def publish_directory(
    staging: Path,
    output_dir: Path,
    temporary: Path,
    *,
    max_file_bytes: int = DEFAULT_FILE_BYTES,
    max_total_bytes: int = DEFAULT_TOTAL_BYTES,
) -> None:
    """Atomically switch a symlink after checking the complete staged directory.

    Versions live beside the public root, so a Vite build follows only the current
    ``public/data`` symlink and never copies historical versions as extra assets.
    """
    check_budget(staging, max_file_bytes=max_file_bytes, max_total_bytes=max_total_bytes)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists() and not output_dir.is_symlink():
        raise ValueError(f"{output_dir} is a directory; migrate it before atomic publication")
    versions = output_dir.parent.parent / f".{output_dir.parent.name}-{output_dir.name}-versions"
    versions.mkdir(exist_ok=True)
    content = hashlib.sha256()
    for path in sorted(staging.rglob("*")):
        if path.is_file():
            name = path.relative_to(staging).as_posix().encode()
            data = path.read_bytes()
            content.update(len(name).to_bytes(8, "big"))
            content.update(name)
            content.update(len(data).to_bytes(8, "big"))
            content.update(data)
    version = versions / content.hexdigest()
    if not version.exists():
        staging.rename(version)
    pointer = temporary / "next"
    pointer.symlink_to(Path("..") / versions.name / version.name, target_is_directory=True)
    os.replace(pointer, output_dir)
