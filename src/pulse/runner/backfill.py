"""Ingest an ordered ISO-week range, then finalize the historical backfill once."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from pulse.contracts.enums import RunType, StageStatus
from pulse.generate.cli import activity_dir, week_range
from pulse.ingest import meta
from pulse.runner.command import run_week
from pulse.runner.run import Runner, WarehouseSink, new_run_id, run_status
from pulse.runner.stage import Clock, Stage, StageContext, StageResult, SystemClock
from pulse.state.sync import clear_local
from pulse.warehouse import WAREHOUSE_FILE, connect


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
    """Acquire the state lock without fetching the old warehouse."""
    from pulse.state import STATE

    return STATE.restore(ctx, skip_remote=True)


def _backfill_restore(ctx: StageContext) -> StageResult:
    from pulse.state import STATE

    return STATE.restore(ctx, rebuild_missing=False)


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
    """Ingest in week order; build, check and publish the complete range at the end.

    A budgeted run checkpoints raw state under projected budget pressure and before a clean stop. A
    continuation restores pending week/run IDs and defect manifests before finishing all
    checks. Small custom DAGs retain weekly execution for focused stage callers/tests.
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
    # Small custom DAGs remain useful for callers testing individual weekly operations.
    if {
        "restore_state",
        "generate",
        "ingest",
        "dbt_build",
        "checks",
        "persist_state",
        "release_lock",
    } <= {s.name for s in stages}:
        return _fast_backfill(
            weeks, data_dir, stages, timer, echo, budget, resume_file, rebuild, require_extract
        )
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


PROGRESS = "backfill-progress.json"
CHECKPOINT_WEEKS = 8


def _fast_backfill(
    weeks: list[str],
    data_dir: Path,
    stages: Sequence[Stage],
    clock: Clock,
    echo: Callable[[str], None],
    budget: timedelta | None,
    resume_file: Path | None,
    rebuild: bool,
    require_extract: bool,
) -> int:
    """Hold one state lock; log ingest/checks by week, build and publish once.

    Progress travels with sources so a fresh runner can check *all* ingested weeks,
    using each original ingest run id and defect manifest, after a budget continuation.
    """
    by_name = {s.name: s for s in stages}
    pending: list[dict[str, str]] = []
    stopped: str | None = None
    failed_week: str | None = None
    loaded = False
    progress = data_dir / "sources" / PROGRESS

    def save_progress() -> None:
        progress.parent.mkdir(parents=True, exist_ok=True)
        progress.write_text(json.dumps({"last": weeks[-1], "pending": pending}, sort_keys=True))

    def execute(ctx: StageContext, selected: Sequence[Stage]) -> StageStatus:
        names = {s.name for s in selected}
        selected = [
            replace(s, depends_on=tuple(d for d in s.depends_on if d in names)) for s in selected
        ]
        report = Runner(
            selected,
            data_dir=data_dir,
            sinks=[WarehouseSink(data_dir / WAREHOUSE_FILE)],
            clock=clock,
        ).run(ctx.iso_week_id, RunType.BACKFILL, ctx.run_id)
        for row in report.rows:
            echo(f"  {ctx.iso_week_id} {row.stage}: {row.status.value} {row.message or ''}")
        return report.status

    def ingest_weeks(outer: StageContext) -> StageResult:
        nonlocal stopped, failed_week, loaded
        if progress.exists():
            saved = json.loads(progress.read_text())
            entries = saved.get("pending", [])
            if saved.get("last") == weeks[-1] and entries and entries[-1]["week"] < weeks[0]:
                if len(week_range(entries[-1]["week"], weeks[0])) != 2:
                    return StageResult(
                        StageStatus.FAILED, message="Continuation skips a checkpoint week."
                    )
                con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
                try:
                    ingested = {
                        (r.iso_week_id, r.run_id)
                        for r in meta.get_run_log(con)
                        if r.stage == "ingest"
                        and r.status in {StageStatus.SUCCESS, StageStatus.WARN, StageStatus.SKIPPED}
                    }
                finally:
                    con.close()
                for entry in entries:
                    if (entry["week"], entry["run_id"]) not in ingested:
                        return StageResult(
                            StageStatus.FAILED,
                            message=(
                                f"Checkpoint progress for {entry['week']} "
                                "is ahead of the warehouse; "
                                "restart from the last persisted ingest week."
                            ),
                        )
                pending.extend(entries)
                for entry in pending:
                    path = data_dir / "defects" / f"{entry['week']}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(entry["defects"])
        started, longest = clock.now(), timedelta(0)
        for index, week in enumerate(weeks):
            if budget is not None and index and clock.now() - started + longest * 1.25 > budget:
                stopped = week
                echo(
                    f"Time budget reached after {index} weeks. "
                    f"Resume with --from {week} --to {weeks[-1]}."
                )
                break
            echo(f"Backfill {index + 1}/{len(weeks)}: {week}")
            week_started = clock.now()
            con = connect(data_dir / WAREHOUSE_FILE, read_only=True)
            try:
                existing = {r.run_id for r in meta.get_run_log(con)}
            finally:
                con.close()
            ctx = replace(
                outer, iso_week_id=week, run_id=new_run_id(RunType.BACKFILL, week, existing)
            )
            if execute(ctx, [by_name["generate"], by_name["ingest"]]) is StageStatus.FAILED:
                failed_week = week
                return StageResult(
                    StageStatus.FAILED, message=f"Ingest failed at {week}; checkpoint unchanged."
                )
            if require_extract and not activity_dir(data_dir / "sources", week).is_dir():
                failed_week = week
                return StageResult(
                    StageStatus.FAILED,
                    message=f"Stopped at {week}: no activity extract was generated.",
                )
            from pulse.runner.stages import load_defects

            pending.append(
                {
                    "week": week,
                    "run_id": ctx.run_id,
                    "defects": load_defects(data_dir, week, clock.now()).model_dump_json(),
                }
            )
            save_progress()
            longest = max(longest, clock.now() - week_started)
            if (
                budget is not None
                and (index + 1) % CHECKPOINT_WEEKS == 0
                and index + 1 < len(weeks)
                and clock.now() - started + longest * (len(weeks) - index - 1) * 1.25 > budget
            ):
                checkpoint = replace(by_name["persist_state"], name="checkpoint_state")
                if execute(outer, [checkpoint]) is StageStatus.FAILED:
                    return StageResult(
                        StageStatus.FAILED, message=f"Checkpoint failed after {week}."
                    )
        loaded = True
        return StageResult(rows_out=len(pending), message="Weekly generate and ingest finished.")

    def per_week(outer: StageContext, name: str) -> StageResult:
        nonlocal failed_week
        if stopped:
            return StageResult(
                StageStatus.SKIPPED, message="Deferred until the final continuation."
            )
        statuses = []
        for entry in pending:
            ctx = replace(outer, iso_week_id=entry["week"], run_id=entry["run_id"])
            stage = by_name[name]
            if name == "narrate" and entry["week"] != weeks[-1]:
                stage = replace(stage, fn=_template_narrate)
            status = execute(ctx, [stage])
            statuses.append(status)
            if status is StageStatus.FAILED:
                failed_week = entry["week"]
                return StageResult(StageStatus.FAILED, message=f"{name} failed at {failed_week}.")
        return StageResult(
            run_status(statuses), message=f"{name} evaluated for {len(pending)} weeks."
        )

    def after_load(stage: Stage) -> Stage:
        fn = stage.fn

        def run(ctx: StageContext) -> StageResult:
            if stopped:
                return StageResult(
                    StageStatus.SKIPPED, message="Deferred until the final continuation."
                )
            return fn(ctx)

        return replace(stage, fn=run)

    def weekly_stage(name: str) -> Callable[[StageContext], StageResult]:
        def run(ctx: StageContext) -> StageResult:
            return per_week(ctx, name)

        return run

    wired: list[Stage] = []
    for stage in stages:
        if stage.name == "restore_state" and rebuild:
            stage = replace(stage, fn=_rebuild_restore)
        elif stage.name == "restore_state" and require_extract:
            stage = replace(stage, fn=_backfill_restore)
        elif stage.name == "generate":
            stage = replace(stage, fn=ingest_weeks)
        elif stage.name == "ingest":
            stage = replace(
                stage, fn=lambda ctx: StageResult(message="Logged separately for each week.")
            )
        elif stage.name in {"checks", "narrate"}:
            stage = replace(stage, fn=weekly_stage(stage.name))
        elif stage.name in {"dbt_build", "export"}:
            stage = after_load(stage)
        wired.append(stage)
    code = run_week(
        weeks[-1],
        data_dir=data_dir,
        run_type=RunType.BACKFILL,
        id_scope=f"range-{weeks[0]}-{weeks[-1]}",
        stages=wired,
        clock=clock,
        echo=echo,
    )
    if code:
        if failed_week:
            echo(f"Stopped at {failed_week}.")
        return code
    if not loaded:
        echo("Backfill did not ingest any weeks (state restore halted the run).")
        return 1
    if stopped:
        if resume_file is not None:
            resume_file.write_text(f"{stopped}\n")
    else:
        echo(f"Backfill complete: {len(pending)} weeks completed.")
    return 0
