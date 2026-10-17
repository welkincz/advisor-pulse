"""Run an ordered ISO-week range through the same pipeline as ``pulse run``."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from pulse.contracts.enums import RunType
from pulse.generate.cli import activity_dir, week_range
from pulse.runner.command import run_week
from pulse.runner.stage import Clock, Stage, StageContext, StageResult
from pulse.state.sync import _clear_local


def _rebuild_restore(ctx: StageContext) -> StageResult:
    """Acquire the state lock for the first week without fetching the old warehouse."""
    from pulse.state import STATE

    return STATE.restore(ctx, skip_remote=True)


def backfill_range(
    first: str,
    last: str,
    *,
    data_dir: Path,
    rebuild: bool = False,
    stages: Sequence[Stage] | None = None,
    clock: Clock | None = None,
    echo: Callable[[str], None] = print,
) -> int:
    """Return nonzero at the first failed week; ``rebuild`` starts with empty local state."""
    weeks = week_range(first, last)
    require_extract = stages is None
    if stages is None:
        from pulse.runner.dag import WEEKLY_STAGES

        stages = WEEKLY_STAGES
    if rebuild:
        _clear_local(data_dir)
    for index, week in enumerate(weeks):
        week_stages = stages
        if rebuild and index == 0:
            week_stages = tuple(
                replace(stage, fn=_rebuild_restore) if stage.name == "restore_state" else stage
                for stage in stages
            )
        echo(f"Backfill {index + 1}/{len(weeks)}: {week}")
        code = run_week(
            week,
            data_dir=data_dir,
            run_type=RunType.BACKFILL,
            stages=week_stages,
            clock=clock,
            echo=echo,
        )
        if code:
            echo(f"Stopped at {week}; {index} weeks completed.")
            return code
        if require_extract and not activity_dir(data_dir / "sources", week).is_dir():
            echo(f"Stopped at {week}: no activity extract was generated.")
            return 1
    echo(f"Backfill complete: {len(weeks)} weeks completed.")
    return 0
