"""Versioned export publication preserves the last good static report."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pulse.export.publish import ExportBudgetError, check_budget, publish_directory


def test_budget_boundaries(tmp_path: Path) -> None:
    (tmp_path / "one").write_bytes(b"a" * 10)
    check_budget(tmp_path, max_file_bytes=10, max_total_bytes=10)
    with pytest.raises(ExportBudgetError, match="per-file"):
        check_budget(tmp_path, max_file_bytes=9, max_total_bytes=10)
    with pytest.raises(ExportBudgetError, match="above"):
        check_budget(tmp_path, max_file_bytes=10, max_total_bytes=9)


def test_atomic_switch_and_identical_version_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public = tmp_path / "public"
    public.mkdir()
    output = public / "data"
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    stage = temporary / "first"
    stage.mkdir()
    (stage / "report.txt").write_text("old")
    publish_directory(stage, output, temporary, max_file_bytes=10, max_total_bytes=10)
    previous = output.resolve()
    assert output.is_symlink()
    assert previous.parent == tmp_path / ".public-data-versions"

    repeat = temporary / "repeat"
    repeat.mkdir()
    (repeat / "report.txt").write_text("old")
    publish_directory(repeat, output, temporary, max_file_bytes=10, max_total_bytes=10)
    assert output.resolve() == previous

    next_stage = temporary / "next_stage"
    next_stage.mkdir()
    (next_stage / "report.txt").write_text("new")
    original_replace = os.replace

    def observe_replace(source: Path, target: Path) -> None:
        assert target == output
        assert (output / "report.txt").read_text() == "old"
        original_replace(source, target)

    monkeypatch.setattr("pulse.export.publish.os.replace", observe_replace)
    publish_directory(next_stage, output, temporary, max_file_bytes=10, max_total_bytes=10)
    assert (output / "report.txt").read_text() == "new"
    assert (previous / "report.txt").read_text() == "old"


def test_rejected_version_preserves_pointer(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    output = public / "data"
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    first = temporary / "first"
    first.mkdir()
    (first / "report.txt").write_text("old")
    publish_directory(first, output, temporary, max_file_bytes=10, max_total_bytes=10)
    previous = output.resolve()
    large = temporary / "large"
    large.mkdir()
    (large / "report.txt").write_text("too large")
    with pytest.raises(ExportBudgetError):
        publish_directory(large, output, temporary, max_file_bytes=1, max_total_bytes=1)
    assert output.resolve() == previous
    assert (output / "report.txt").read_text() == "old"
