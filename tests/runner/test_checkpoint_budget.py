"""Checkpoint decisions use injected elapsed time and preserve stop-time durability."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pulse.contracts.enums import StageStatus
from pulse.generate.cli import iso_week, week_start
from pulse.runner.backfill import PROGRESS, backfill_range
from pulse.runner.stage import Stage, StageResult
from pulse.warehouse import connect


class SimClock:
    def __init__(self):
        self.at = datetime(2026, 1, 5, tzinfo=UTC)

    def now(self):
        return self.at

    def sleep(self, seconds):
        self.at += timedelta(seconds=seconds)


def scenario(root, *, count=16, budget=180, week_seconds=600, persist_seconds=0, fail_at=None):
    clock = SimClock()
    snapshots = []
    first = "2024-W41"
    last = iso_week(week_start(first) + timedelta(weeks=count - 1))
    resume = root / "next"

    def operation(name):
        def run(ctx):
            if name == "ingest":
                clock.sleep(
                    week_seconds(ctx.iso_week_id) if callable(week_seconds) else week_seconds
                )
            if name == "persist_state":
                pending = json.loads((root / "sources" / PROGRESS).read_text())["pending"]
                snapshots.append(len(pending))
                clock.sleep(persist_seconds)
                if len(pending) == fail_at:
                    return StageResult(StageStatus.FAILED, message="Synthetic checkpoint failure")
            return StageResult()

        return run

    names = (
        "restore_state",
        "generate",
        "ingest",
        "dbt_build",
        "checks",
        "export",
        "persist_state",
        "release_lock",
    )
    stages = tuple(
        Stage(
            name, name, operation(name), (names[i - 1],) if i else (), always=name == "release_lock"
        )
        for i, name in enumerate(names)
    )
    code = backfill_range(
        first,
        last,
        data_dir=root,
        stages=stages,
        clock=clock,
        budget=timedelta(minutes=budget) if budget is not None else None,
        resume_file=resume,
        echo=lambda _: None,
    )
    with connect(root / "warehouse.duckdb", read_only=True) as con:
        logs = con.execute("select stage, status from meta.run_log").fetchall()
    return code, snapshots, resume, logs, clock


@pytest.mark.parametrize("budget", [None, 180, 1000])
def test_forecast_that_fits_skips_periodic_persistence(tmp_path: Path, budget) -> None:
    # After week8: 80 elapsed + 8 remaining * 10 * 1.25 = 180 minutes.
    code, snapshots, resume, logs, _ = scenario(tmp_path, budget=budget)
    assert code == 0
    assert snapshots == [16]  # Final persist still happens; equality is not budget pressure.
    assert not resume.exists()
    assert not any(stage == "checkpoint_state" for stage, _ in logs)


def test_pressure_retains_periodic_checkpoint_and_stop_checkpoint(tmp_path: Path) -> None:
    code, snapshots, resume, logs, _ = scenario(tmp_path, budget=100)
    assert code == 0
    assert snapshots == [8, 9]
    assert resume.read_text() == "2024-W50\n"
    assert ("checkpoint_state", "SUCCESS") in logs
    assert ("dbt_build", "SKIPPED") in logs
    assert ("export", "SKIPPED") in logs


@pytest.mark.parametrize("budget,fail_at", [(100, 8), (25, 2)])
def test_failed_periodic_or_stop_persist_never_writes_resume(tmp_path, budget, fail_at):
    code, snapshots, resume, logs, _ = scenario(tmp_path, budget=budget, fail_at=fail_at)
    assert code == 1
    assert snapshots == [fail_at]
    assert not resume.exists()
    assert ("release_lock", "SUCCESS") in logs


def test_projection_uses_longest_week_instead_of_last_week(tmp_path):
    def seconds(week):
        return 1800 if week == "2024-W41" else 600

    code, snapshots, resume, _, _ = scenario(tmp_path, budget=250, week_seconds=seconds)
    assert code == 0
    assert snapshots == [8, 16]  # Forecast 400min, even though actual ingestion fits in 180min.
    assert not resume.exists()


def test_overrunning_last_week_does_not_duplicate_final_persist(tmp_path):
    def seconds(week):
        return 1800 if week == "2024-W48" else 60

    code, snapshots, resume, logs, _ = scenario(tmp_path, count=8, budget=20, week_seconds=seconds)
    assert code == 0
    assert snapshots == [8]
    assert not resume.exists()
    assert not any(stage == "checkpoint_state" for stage, _ in logs)
