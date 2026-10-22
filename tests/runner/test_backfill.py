"""Backfill executes the weekly runner in order and can rebuild from empty state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pulse.cli import app
from pulse.contracts.enums import RunType, StageStatus
from pulse.generate.cli import Sizes, activity_dir, generate_weeks, week_range
from pulse.runner.backfill import backfill_range
from pulse.runner.stage import Stage, StageContext, StageResult
from pulse.warehouse import WAREHOUSE_FILE


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 4, 20, tzinfo=UTC)

    def sleep(self, seconds: float) -> None:
        pass


def test_eight_weeks_use_backfill_run_type_and_previous_state(tmp_path: Path) -> None:
    seen: list[tuple[str, RunType, int]] = []

    def work(ctx: StageContext) -> StageResult:
        history = ctx.data_dir / "history"
        previous = history.read_text().splitlines() if history.exists() else []
        seen.append((ctx.iso_week_id, ctx.run_type, len(previous)))
        history.write_text("\n".join([*previous, ctx.iso_week_id]))
        return StageResult()

    stages = (Stage("work", "Work", work),)
    lines: list[str] = []
    assert (
        backfill_range(
            "2026-W08",
            "2026-W15",
            data_dir=tmp_path,
            stages=stages,
            clock=Clock(),
            echo=lines.append,
        )
        == 0
    )
    assert seen == [
        (week, RunType.BACKFILL, i) for i, week in enumerate(week_range("2026-W08", "2026-W15"))
    ]
    assert len((tmp_path / "history").read_text().splitlines()) == 8
    assert "8 weeks completed" in lines[-1]


def test_eight_week_backfill_writes_real_small_source_extracts(tmp_path: Path) -> None:
    def generate(ctx: StageContext) -> StageResult:
        count = generate_weeks(
            ctx.data_dir,
            [ctx.iso_week_id],
            seed=42,
            sizes=Sizes(advisors=12, clients=100),
            echo=lambda _: None,
        )
        return StageResult(rows_out=count)

    assert (
        backfill_range(
            "2026-W08",
            "2026-W15",
            data_dir=tmp_path,
            stages=(Stage("generate", "Generate", generate),),
            clock=Clock(),
            echo=lambda _: None,
        )
        == 0
    )
    for week in week_range("2026-W08", "2026-W15"):
        assert activity_dir(tmp_path / "sources", week).is_dir()
        assert (tmp_path / "defects" / f"{week}.json").is_file()


def test_failed_week_stops_range_and_returns_nonzero(tmp_path: Path) -> None:
    seen: list[str] = []

    def work(ctx: StageContext) -> StageResult:
        seen.append(ctx.iso_week_id)
        return StageResult(
            StageStatus.FAILED if ctx.iso_week_id == "2026-W10" else StageStatus.SUCCESS
        )

    lines: list[str] = []
    assert (
        backfill_range(
            "2026-W08",
            "2026-W15",
            data_dir=tmp_path,
            stages=(Stage("work", "Work", work),),
            clock=Clock(),
            echo=lines.append,
        )
        == 1
    )
    assert seen == ["2026-W08", "2026-W09", "2026-W10"]
    assert "Stopped at 2026-W10" in lines[-1]


@pytest.mark.parametrize("first,last", [("2026-W00", "2026-W02"), ("2026-W10", "2026-W09")])
def test_invalid_range_is_rejected_before_state_changes(
    tmp_path: Path, first: str, last: str
) -> None:
    with pytest.raises(ValueError):
        backfill_range(first, last, data_dir=tmp_path)
    assert not list(tmp_path.iterdir())


def test_rebuild_clears_previous_state_before_first_week(tmp_path: Path) -> None:
    (tmp_path / WAREHOUSE_FILE).write_text("stale")
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "stale.csv").write_text("stale")
    (tmp_path / "defects").mkdir()
    (tmp_path / "defects" / "stale.json").write_text("stale")
    (tmp_path / "defects.json").write_text("stale")
    seen: list[tuple[str, bool, bool, int]] = []

    def work(ctx: StageContext) -> StageResult:
        history = ctx.data_dir / "history"
        previous = history.read_text().splitlines() if history.exists() else []
        seen.append(
            (
                ctx.iso_week_id,
                (ctx.data_dir / "sources" / "stale.csv").exists(),
                (ctx.data_dir / "defects.json").exists(),
                len(previous),
            )
        )
        history.write_text("\n".join([*previous, ctx.iso_week_id]))
        return StageResult()

    stages = (
        Stage("restore_state", "Restore", lambda c: StageResult()),
        Stage("work", "Work", work, ("restore_state",)),
    )
    assert (
        backfill_range(
            "2026-W08",
            "2026-W09",
            data_dir=tmp_path,
            rebuild=True,
            stages=stages,
            clock=Clock(),
            echo=lambda _: None,
        )
        == 0
    )
    assert seen == [("2026-W08", False, False, 0), ("2026-W09", False, False, 1)]


def test_cli_backfill_calls_runner_and_propagates_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import pulse.runner.backfill as module

    seen: list[tuple[str, str, bool]] = []

    def fake(first: str, last: str, *, data_dir: Path, rebuild: bool, **_: object) -> int:
        seen.append((first, last, rebuild))
        return 1

    monkeypatch.setattr(module, "backfill_range", fake)
    result = CliRunner().invoke(
        app, ["backfill", "--from", "2026-W08", "--to", "2026-W15", "--rebuild"]
    )
    assert result.exit_code == 1
    assert seen == [("2026-W08", "2026-W15", True)]


def test_default_pipeline_cannot_report_success_without_an_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pulse.runner.dag as dag

    monkeypatch.setattr(dag, "WEEKLY_STAGES", (Stage("noop", "No work", lambda c: StageResult()),))
    lines: list[str] = []
    assert (
        backfill_range("2026-W08", "2026-W08", data_dir=tmp_path, clock=Clock(), echo=lines.append)
        == 1
    )
    assert "no activity extract" in lines[-1]


def test_default_backfill_uses_templates_until_the_final_week(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pulse.narrative.stage as narrative_stage
    import pulse.runner.backfill as module

    clients: list[tuple[str, object]] = []

    def fake_narrate(
        ctx: StageContext, client_factory: Callable[[], object] = lambda: "model"
    ) -> StageResult:
        client = client_factory()
        clients.append((ctx.iso_week_id, client))
        return StageResult(StageStatus.WARN if client is None else StageStatus.SUCCESS, rows_out=2)

    def fake_run_week(
        week: str,
        *,
        data_dir: Path,
        run_type: RunType,
        stages: tuple[Stage, ...],
        clock: Clock | None,
        echo: object,
    ) -> int:
        assert run_type is RunType.BACKFILL
        narrate = next(s for s in stages if s.name == "narrate")
        result = narrate.fn(StageContext("test-run", run_type, week, data_dir, clock or Clock()))
        assert result.rows_out == 2
        if week != "2026-W10":
            assert "template" in (result.message or "")
            assert result.status is StageStatus.SUCCESS  # templates are the plan for history
        return 0

    monkeypatch.setattr(narrative_stage, "narrate", fake_narrate)
    monkeypatch.setattr(module, "run_week", fake_run_week)
    monkeypatch.setattr(module, "activity_dir", lambda *_: tmp_path)
    assert backfill_range("2026-W08", "2026-W10", data_dir=tmp_path, clock=Clock()) == 0
    assert clients == [
        ("2026-W08", None),
        ("2026-W09", None),
        ("2026-W10", "model"),
    ]


class TickingClock:
    """Each week's single stage advances the clock by that week's minutes."""

    def __init__(self, minutes: list[int]) -> None:
        self.at = datetime(2026, 4, 20, tzinfo=UTC)
        self.minutes = minutes

    def now(self) -> datetime:
        return self.at

    def sleep(self, seconds: float) -> None:
        pass


def _ticking_stages(clock: TickingClock, seen: list[str]) -> tuple[Stage, ...]:
    def work(ctx: StageContext) -> StageResult:
        seen.append(ctx.iso_week_id)
        clock.at += timedelta(minutes=clock.minutes[len(seen) - 1])
        return StageResult()

    return (Stage("work", "Work", work),)


def test_budget_stops_between_weeks_and_names_where_to_resume(tmp_path: Path) -> None:
    clock, seen, lines = TickingClock([50, 60, 55, 70, 40]), [], []
    resume = tmp_path / "resume.txt"
    code = backfill_range(
        "2026-W08",
        "2026-W12",
        data_dir=tmp_path,
        stages=_ticking_stages(clock, seen),
        clock=clock,
        echo=lines.append,
        budget=timedelta(minutes=200),
        resume_file=resume,
    )
    # 165 min used after three weeks; the next week is budgeted at 60 × 1.25 = 75 > 35 left.
    assert code == 0
    assert seen == ["2026-W08", "2026-W09", "2026-W10"]
    assert resume.read_text() == "2026-W11\n"
    assert lines[-1] == (
        "Time budget reached after 3 weeks (165 min of 200 min). "
        "Resume with --from 2026-W11 --to 2026-W12."
    )


def test_budget_that_fits_runs_everything_and_leaves_no_resume_file(tmp_path: Path) -> None:
    clock, seen = TickingClock([10, 10, 10]), []
    resume = tmp_path / "resume.txt"
    resume.write_text("2026-W01\n")  # left over from an earlier stopped run
    code = backfill_range(
        "2026-W08",
        "2026-W10",
        data_dir=tmp_path,
        stages=_ticking_stages(clock, seen),
        clock=clock,
        echo=lambda _: None,
        budget=timedelta(minutes=200),
        resume_file=resume,
    )
    assert code == 0
    assert seen == ["2026-W08", "2026-W09", "2026-W10"]
    assert not resume.exists()


def test_cli_passes_the_budget_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import pulse.runner.backfill as module

    seen: dict[str, object] = {}

    def fake(first: str, last: str, **kwargs: object) -> int:
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(module, "backfill_range", fake)
    result = CliRunner().invoke(
        app,
        [
            "backfill",
            "--from",
            "2026-W08",
            "--to",
            "2026-W15",
            "--budget-minutes",
            "320",
            "--resume-file",
            str(tmp_path / "next"),
        ],
    )
    assert result.exit_code == 0
    assert seen["budget"] == timedelta(minutes=320)
    assert seen["resume_file"] == tmp_path / "next"


def test_a_failed_week_wins_over_the_budget(tmp_path: Path) -> None:
    resume = tmp_path / "resume.txt"

    def fail(ctx: StageContext) -> StageResult:
        return StageResult(StageStatus.FAILED, message="boom")

    code = backfill_range(
        "2026-W08",
        "2026-W12",
        data_dir=tmp_path,
        stages=(Stage("work", "Work", fail),),
        clock=Clock(),
        echo=lambda _: None,
        budget=timedelta(minutes=200),
        resume_file=resume,
    )
    assert code != 0
    assert not resume.exists()
