"""Execute a stage DAG for one ISO week, retrying transient errors and logging every attempt."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from tenacity.wait import wait_base

from pulse.contracts import patterns
from pulse.contracts.enums import RunType, StageStatus
from pulse.contracts.meta import RunLogRow
from pulse.ingest import meta
from pulse.runner.dag import downstream, execution_order
from pulse.runner.stage import Clock, Stage, StageContext, StageResult, SystemClock
from pulse.warehouse import connect, init_warehouse, transaction

# Worst first. A run's status is the worst final status among its stages.
SEVERITY = (StageStatus.FAILED, StageStatus.WARN, StageStatus.SUCCESS, StageStatus.SKIPPED)

DEFAULT_WAIT: wait_base = wait_exponential_jitter(multiplier=2, max=30, jitter=1)


class RunLogSink(Protocol):
    def write(self, row: RunLogRow) -> None: ...


class MemorySink:
    def __init__(self) -> None:
        self.rows: list[RunLogRow] = []

    def write(self, row: RunLogRow) -> None:
        self.rows.append(row)


class WarehouseSink:
    """Upserts into ``meta.run_log``.

    Each write re-sends every row of the run so far. restore_state may replace the warehouse
    file mid-run, and the next write puts the earlier rows back.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = path
        self._rows: dict[tuple[str, str, int], RunLogRow] = {}

    def write(self, row: RunLogRow) -> None:
        self._rows[(row.run_id, row.stage, row.attempt)] = row
        con = connect(self.path)
        try:
            init_warehouse(con)
            with transaction(con):
                for r in self._rows.values():
                    meta.write_run_log(con, r)
        finally:
            con.close()


@dataclass(frozen=True)
class RunReport:
    run_id: str
    run_type: RunType
    iso_week_id: str
    status: StageStatus
    rows: list[RunLogRow]

    @property
    def failed(self) -> bool:
        return self.status is StageStatus.FAILED


def run_status(statuses: Iterable[StageStatus]) -> StageStatus:
    present = set(statuses)
    return next((s for s in SEVERITY if s in present), StageStatus.SKIPPED)


def new_run_id(run_type: RunType, iso_week_id: str, existing: Iterable[str]) -> str:
    """``weekly-2026-W40-1``; the suffix counts earlier runs of the same type and week."""
    prefix = f"{run_type.value.lower()}-{iso_week_id}-"
    taken = [int(r[len(prefix) :]) for r in existing if re.fullmatch(re.escape(prefix) + r"\d+", r)]
    return f"{prefix}{max(taken, default=0) + 1}"


def iso_week_id(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def resolve_week(value: str | None, today: date) -> str:
    """``None`` or ``'last'`` means the last complete ISO week (ending the Sunday before today)."""
    if value is None or value == "last":
        return iso_week_id(today - timedelta(days=today.isoweekday()))
    if not re.fullmatch(patterns.ISO_WEEK_ID, value):
        raise ValueError(f"Not an ISO week id: {value!r} (expected e.g. 2026-W40)")
    return value


def plan(stages: Sequence[Stage]) -> list[str]:
    """One line per stage in execution order, for ``--dry-run``."""
    lines = []
    for i, stage in enumerate(execution_order(stages), 1):
        after = f" after {', '.join(stage.depends_on)}" if stage.depends_on else ""
        retry = f", up to {stage.max_attempts} attempts" if stage.max_attempts > 1 else ""
        lines.append(f"{i}. {stage.name} ({stage.label}){after}{retry}")
    return lines


class Runner:
    def __init__(
        self,
        stages: Sequence[Stage],
        *,
        data_dir: Path,
        sinks: Sequence[RunLogSink] = (),
        clock: Clock | None = None,
        wait: wait_base = DEFAULT_WAIT,
        git_sha: str | None = None,
    ) -> None:
        self.stages = execution_order(stages)
        self.data_dir = data_dir
        self.sinks = sinks
        self.clock = clock or SystemClock()
        self.wait = wait
        self.git_sha = git_sha

    def run(self, iso_week_id: str, run_type: RunType, run_id: str) -> RunReport:
        ctx = StageContext(run_id, run_type, iso_week_id, self.data_dir, self.clock)
        rows: list[RunLogRow] = []
        finals: dict[str, StageStatus] = {}
        blocked_by: dict[str, str] = {}
        halted_by: StageResult | None = None
        halted_at = ""

        for stage in self.stages:
            if halted_by is not None:
                skip = f"Run stopped at {halted_at}: {halted_by.message or 'halted'}"
            elif stage.name in blocked_by and not stage.always:
                skip = f"Upstream stage {blocked_by[stage.name]} failed."
            else:
                skip = None
            if skip is not None:
                now = self.clock.now()
                row = self._row(ctx, stage.name, 1, StageStatus.SKIPPED, now)
                row = row.model_copy(update={"ended_at": now, "duration_ms": 0, "message": skip})
                self._emit(rows, row)
                finals[stage.name] = StageStatus.SKIPPED
                continue

            result = self._run_stage(ctx, stage, rows)
            finals[stage.name] = result.status
            if result.status is StageStatus.FAILED:
                for name in downstream(self.stages, stage.name):
                    blocked_by.setdefault(name, stage.name)
            if result.halt:
                halted_by, halted_at = result, stage.name

        return RunReport(run_id, run_type, iso_week_id, run_status(finals.values()), rows)

    def _run_stage(self, ctx: StageContext, stage: Stage, rows: list[RunLogRow]) -> StageResult:
        retrying = Retrying(
            stop=stop_after_attempt(stage.max_attempts),
            wait=self.wait,
            retry=retry_if_exception_type(stage.retry_on),
            sleep=self.clock.sleep,
            reraise=True,
        )
        try:
            for attempt in retrying:
                with attempt:
                    n = attempt.retry_state.attempt_number
                    return self._attempt(ctx, stage, n, rows)
        except Exception:
            return StageResult(StageStatus.FAILED)
        raise AssertionError("unreachable: tenacity yields at least one attempt")

    def _attempt(
        self, ctx: StageContext, stage: Stage, n: int, rows: list[RunLogRow]
    ) -> StageResult:
        started = self.clock.now()
        self._emit(rows, self._row(ctx, stage.name, n, StageStatus.RUNNING, started))
        try:
            result = stage.fn(ctx)
            if not isinstance(result, StageResult):
                raise TypeError(f"Stage returned {type(result).__name__}, not StageResult")
        except Exception as exc:
            retrying = isinstance(exc, stage.retry_on) and n < stage.max_attempts
            message = f"{type(exc).__name__}: {exc}" + ("; retrying." if retrying else "")
            self._finish(
                ctx, stage.name, n, started, StageResult(StageStatus.FAILED, message=message), rows
            )
            raise
        self._finish(ctx, stage.name, n, started, result, rows)
        return result

    def _finish(
        self,
        ctx: StageContext,
        stage: str,
        n: int,
        started: datetime,
        result: StageResult,
        rows: list[RunLogRow],
    ) -> None:
        ended = self.clock.now()
        row = self._row(ctx, stage, n, result.status, started).model_copy(
            update={
                "ended_at": ended,
                "duration_ms": max(0, int((ended - started).total_seconds() * 1000)),
                "rows_in": result.rows_in,
                "rows_out": result.rows_out,
                "rows_quarantined": result.rows_quarantined,
                "message": result.message,
            }
        )
        self._emit(rows, row)

    def _row(
        self, ctx: StageContext, stage: str, n: int, status: StageStatus, started: datetime
    ) -> RunLogRow:
        return RunLogRow(
            run_id=ctx.run_id,
            run_type=ctx.run_type,
            iso_week_id=ctx.iso_week_id,
            stage=stage,
            attempt=n,
            status=status,
            started_at=started,
            git_sha=self.git_sha,
        )

    def _emit(self, rows: list[RunLogRow], row: RunLogRow) -> None:
        """Record a row; a final row replaces the RUNNING row of the same attempt."""
        if rows and (rows[-1].stage, rows[-1].attempt) == (row.stage, row.attempt):
            rows[-1] = row
        else:
            rows.append(row)
        for sink in self.sinks:
            sink.write(row)
