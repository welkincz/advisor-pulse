"""Run an ordered ISO-week range through the same pipeline as ``pulse run``."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from pulse.contracts.enums import RunType, StageStatus
from pulse.generate.cli import activity_dir, week_range
from pulse.runner.command import run_week
from pulse.runner.stage import Clock, Stage, StageContext, StageResult, SystemClock
from pulse.state.sync import clear_local


def _template_narrate(ctx: StageContext) -> StageResult:
    """Historical backfill weeks write grounded templates without model calls.

    Skipping the model is the plan for history, not a problem, so the stage succeeds; a
    warning here would mark every backfilled week and teach readers to ignore warnings.
    """
    from pulse.narrative.stage import narrate

    result = narrate(ctx, client_factory=lambda: None)
    if result.rows_out is not None:
        return replace(
            result,
            status=StageStatus.SUCCESS if result.status is StageStatus.WARN else result.status,
            message=(
                f"Backfill history: wrote {result.rows_out} template narratives; model skipped."
            ),
        )
    return result


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
    budget: timedelta | None = None,
    resume_file: Path | None = None,
) -> int:
    """Return nonzero at the first failed week; ``rebuild`` starts with empty local state.

    With a ``budget``, stop cleanly between weeks once the next one might not fit: each week
    has released the state lock and persisted its state, so a later run continues with
    ``--from`` the week named in the message (and written to ``resume_file``). This keeps a
    long rebuild inside a CI job's time limit instead of being cancelled mid-week (#206).
    """
    weeks = week_range(first, last)
    timer = clock or SystemClock()
    started, longest = timer.now(), timedelta(0)
    if resume_file is not None:
        resume_file.unlink(missing_ok=True)
    require_extract = stages is None
    if stages is None:
        from pulse.runner.dag import WEEKLY_STAGES

        stages = WEEKLY_STAGES
    if rebuild:
        clear_local(data_dir)
    for index, week in enumerate(weeks):
        week_stages = stages
        if require_extract and index < len(weeks) - 1:
            week_stages = tuple(
                replace(stage, fn=_template_narrate) if stage.name == "narrate" else stage
                for stage in week_stages
            )
        if rebuild and index == 0:
            week_stages = tuple(
                replace(stage, fn=_rebuild_restore) if stage.name == "restore_state" else stage
                for stage in week_stages
            )
        if budget is not None and index > 0:
            elapsed = timer.now() - started
            # The next week is budgeted at the slowest so far plus a quarter.
            if elapsed + longest * 1.25 > budget:
                echo(
                    f"Time budget reached after {index} weeks ({_minutes(elapsed)} of "
                    f"{_minutes(budget)}). Resume with --from {week} --to {last}."
                )
                if resume_file is not None:
                    resume_file.write_text(f"{week}\n")
                return 0
        echo(f"Backfill {index + 1}/{len(weeks)}: {week}")
        week_started = timer.now()
        code = run_week(
            week,
            data_dir=data_dir,
            run_type=RunType.BACKFILL,
            stages=week_stages,
            clock=clock,
            echo=echo,
        )
        longest = max(longest, timer.now() - week_started)
        if code:
            echo(f"Stopped at {week}; {index} weeks completed.")
            return code
        if require_extract and not activity_dir(data_dir / "sources", week).is_dir():
            echo(f"Stopped at {week}: no activity extract was generated.")
            return 1
    echo(f"Backfill complete: {len(weeks)} weeks completed.")
    return 0


def _minutes(span: timedelta) -> str:
    return f"{span.total_seconds() / 60:.0f} min"
