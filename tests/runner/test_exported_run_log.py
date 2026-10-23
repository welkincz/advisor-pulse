"""#281: the site's run_log.json records every stage's final outcome, export's included."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pulse.contracts.enums import StageStatus
from pulse.contracts.exports import RunLogExport
from pulse.export.publish import publish_directory
from pulse.export.web import publish_run_log
from pulse.runner import WEEKLY_STAGES, Stage, StageContext, StageResult, stages
from pulse.runner.command import run_week
from pulse.runner.run_log import export_from_warehouse
from pulse.warehouse import WAREHOUSE_FILE, connect

WEEK = "2026-W40"
RUN_ID = f"manual-{WEEK}-1"
T0 = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)

StageFn = Callable[[StageContext], StageResult]


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def now(self) -> datetime:
        self.t += timedelta(milliseconds=10)
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


def ok(ctx: StageContext) -> StageResult:
    return StageResult()


def snapshot_export(ctx: StageContext) -> StageResult:
    """What the real export stage does with the run log: publish it mid-stage."""
    con = connect(ctx.data_dir / WAREHOUSE_FILE, read_only=True)
    try:
        doc = export_from_warehouse(con, ctx.clock.now(), current_run_id=ctx.run_id)
    finally:
        con.close()
    publish_run_log(stages.export_dir(), doc)
    return StageResult(rows_out=1)


def weekly(**overrides: StageFn) -> list[Stage]:
    return [replace(s, fn=overrides.get(s.name, ok)) for s in WEEKLY_STAGES]


def exported() -> RunLogExport:
    return RunLogExport.model_validate_json((stages.export_dir() / "run_log.json").read_text())


def go(data_dir: Path, stage_list: list[Stage], out: list[str] | None = None) -> int:
    sink = out if out is not None else []
    return run_week(WEEK, data_dir=data_dir, stages=stage_list, clock=Clock(), echo=sink.append)


def assert_all_final(doc: RunLogExport) -> None:
    latest = doc.runs[0]
    assert latest.run_id == RUN_ID
    assert [a.stage for a in latest.stages] == [s.name for s in WEEKLY_STAGES]
    for attempt in latest.stages:
        assert attempt.status is not StageStatus.RUNNING, attempt.stage
        assert attempt.ended_at is not None, attempt.stage
    assert latest.ended_at is not None


def test_exported_run_log_shows_every_stage_final(tmp_path: Path) -> None:
    assert go(tmp_path, weekly(export=snapshot_export)) == 0
    doc = exported()
    assert_all_final(doc)
    by_stage = {a.stage: a for a in doc.runs[0].stages}
    assert by_stage["export"].status is StageStatus.SUCCESS
    assert by_stage["export"].rows_out == 1
    assert by_stage["release_lock"].status is StageStatus.SUCCESS
    assert doc.runs[0].status is StageStatus.SUCCESS


def test_a_failed_export_is_recorded_and_keeps_the_previous_data(tmp_path: Path) -> None:
    # The last good weekly report, published the way export publishes it.
    staging, scratch = tmp_path / "previous", tmp_path / "scratch"
    staging.mkdir()
    scratch.mkdir()
    (staging / "manifest.json").write_text("last good manifest")
    (staging / "run_log.json").write_text("{}")
    publish_directory(staging, stages.export_dir(), scratch)

    def broken_export(ctx: StageContext) -> StageResult:
        snapshot_export(ctx)
        raise OSError("disk full")

    out: list[str] = []
    assert go(tmp_path, weekly(export=broken_export), out) == 1
    doc = exported()
    assert_all_final(doc)
    by_stage = {a.stage: a for a in doc.runs[0].stages}
    assert by_stage["export"].status is StageStatus.FAILED
    assert by_stage["export"].message == "OSError: disk full"
    assert by_stage["publish_sheets"].status is StageStatus.SKIPPED
    assert by_stage["release_lock"].status is StageStatus.SUCCESS
    assert doc.runs[0].status is StageStatus.FAILED
    assert (stages.export_dir() / "manifest.json").read_text() == "last good manifest"
    assert out[-1] == f"{RUN_ID}: FAILED"


def test_a_skipped_export_publishes_nothing(tmp_path: Path) -> None:
    def skipped(ctx: StageContext) -> StageResult:
        return StageResult(StageStatus.SKIPPED, message="Marts not built yet.")

    assert go(tmp_path, weekly(export=skipped)) == 0
    assert not stages.export_dir().exists()


def test_a_failed_refresh_fails_the_command_and_says_why(tmp_path: Path) -> None:
    # A plain directory (not the atomic symlink) cannot be republished.
    stages.export_dir().mkdir(parents=True)

    def plain_dir_export(ctx: StageContext) -> StageResult:
        return StageResult(rows_out=0)

    out: list[str] = []
    assert go(tmp_path, weekly(export=plain_dir_export), out) == 1
    assert any(
        line.startswith("Could not republish run_log.json with final stage statuses: ValueError")
        for line in out
    )
    assert out[-1] == f"{RUN_ID}: SUCCESS"


@pytest.mark.integration
def test_real_run_on_fixtures_exports_every_stage_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real DAG on an empty data dir (generate writes a small world), as ``make run``."""
    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path))
    assert go(tmp_path, list(WEEKLY_STAGES)) == 0
    assert (stages.export_dir() / "manifest.json").exists()
    assert_all_final(exported())
